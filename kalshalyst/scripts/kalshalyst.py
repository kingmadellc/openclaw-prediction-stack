"""Kalshalyst — Claude-powered contrarian estimation.

Pipeline:
  Phase 1: FETCH — Kalshi markets with blocklist + timeframe filtering
  Phase 2: CLASSIFY — Disabled (Qwen unreliable). Markets pass through with defaults.
  Phase 3: ESTIMATE — Claude Sonnet contrarian estimation (sees price, finds disagreements)
  Phase 4: EDGE — Raw edge calculation (limit order assumption, no spread penalty)
  Phase 5: CACHE + ALERT — Write cache, alert on high-edge opportunities

Key change from prior versions: Claude now sees the market price and is prompted to find
reasons the market is wrong. Blind estimation produced consensus-matching
estimates with zero edge. Contrarian mode produces opinionated directional calls.
Falls back to Qwen if Claude is unavailable (offline/cooldown).

Usage:
    python kalshalyst.py [--dry-run] [--force]
"""

import json
import re
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Kalshalyst: %(message)s'
)
logger = logging.getLogger(__name__)


def _load_market_filter_config() -> dict:
    """Load market filter config from ~/prompt-lab/market_filter.json."""
    paths = [
        Path.home() / "prompt-lab" / "market_filter.json",
        Path.home() / ".openclaw" / "market_filter.json",
    ]

    for p in paths:
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
                logger.info(
                    "Market filter config loaded from %s (mode=%s)",
                    p,
                    cfg.get("filter_mode", "unknown"),
                )
                return cfg
            except Exception as e:
                logger.warning("Failed to load market filter config from %s: %s", p, e)

    logger.info("No market filter config found — using defaults (no category/boost filtering)")
    return {}


# Load market filter config (used in _apply_market_filter)
_MARKET_FILTER_CFG = _load_market_filter_config()

DEMO_SCAN_INSIGHTS = [
    {
        "ticker": "FEDCUTS-2026-Q3",
        "title": "Will the Fed cut rates by September 2026?",
        "side": "YES",
        "market_prob": 0.43,
        "estimated_prob": 0.57,
        "edge_pct": 14.0,
        "effective_edge_pct": 14.0,
        "confidence": 0.68,
        "reasoning": "Late-cycle growth scare risk is underpriced versus current inflation momentum.",
    },
    {
        "ticker": "BTC-2026-120K",
        "title": "Will Bitcoin hit $120k before July 2026?",
        "side": "YES",
        "market_prob": 0.39,
        "estimated_prob": 0.49,
        "edge_pct": 10.0,
        "effective_edge_pct": 10.0,
        "confidence": 0.61,
        "reasoning": "ETF flows and reflexive treasury demand give upside more paths than the market is pricing.",
    },
    {
        "ticker": "STABLECOIN-REG-2026",
        "title": "Will Congress pass stablecoin legislation in 2026?",
        "side": "YES",
        "market_prob": 0.34,
        "estimated_prob": 0.42,
        "edge_pct": 8.0,
        "effective_edge_pct": 8.0,
        "confidence": 0.57,
        "reasoning": "Bipartisan payment-rail incentives remain stronger than headline gridlock suggests.",
    },
]


def _ledger_context() -> dict:
    """Return what the local trade ledger still knows."""
    try:
        from trade_ledger import get_summary as get_ledger_summary

        summary = get_ledger_summary()
        return {
            "ledger_open_positions": summary.get("open_positions", 0),
            "ledger_deployed_usd": summary.get("total_deployed_usd", 0.0),
            "ledger_tickers": sorted(summary.get("positions", {}).keys()),
        }
    except Exception as e:
        return {
            "ledger_open_positions": 0,
            "ledger_deployed_usd": 0.0,
            "ledger_tickers": [],
            "ledger_error": str(e)[:200],
        }


def _write_cache(payload: dict) -> None:
    """Write cache payload for downstream consumers."""
    cache_dir = Path.home() / ".openclaw" / "state"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "kalshalyst_cache.json"
    with open(cache_path, "w") as f:
        json.dump(payload, f, indent=2)


def _write_fail_loud_cache(reason: str, known: str = "") -> None:
    """Write an explicit uncertain cache entry instead of an empty success."""
    message = "I don't know current opportunities"
    if known:
        message += f" — {known}"

    payload = {
        "insights": [],
        "macro_count": 0,
        "total_scanned": 0,
        "scanner_version": "1.0.0",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "status": "uncertain",
        "message": message,
        "reason": reason,
        **_ledger_context(),
    }
    try:
        _write_cache(payload)
    except OSError as e:
        logger.warning("Could not write fail-loud cache: %s", e)


def _write_demo_cache() -> None:
    """Write sample opportunities so first-run users can preview output."""
    payload = {
        "insights": DEMO_SCAN_INSIGHTS,
        "macro_count": len(DEMO_SCAN_INSIGHTS),
        "total_scanned": 18,
        "scanner_version": "1.0.0-demo",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "status": "demo",
        "message": "Demo opportunities shown because Kalshi credentials are not configured yet.",
        **_ledger_context(),
    }
    try:
        _write_cache(payload)
    except OSError as e:
        logger.warning("Could not write demo cache: %s", e)


def _show_demo_scan(next_step: str) -> None:
    """Render a friendly preview when live scanning is unavailable."""
    _write_demo_cache()
    _print_top_opportunities(DEMO_SCAN_INSIGHTS, "TOP 3 EDGE OPPORTUNITIES (DEMO)")
    logger.info("")
    logger.info("%s", next_step)


def _verify_kalshi_client(client) -> None:
    """Verify auth with a raw API call that avoids SDK model parsing bugs."""
    url = "https://api.elections.kalshi.com/trade-api/v2/portfolio/positions?limit=1"
    resp = client.call_api("GET", url)
    payload = json.loads(resp.read())
    # Kalshi returns {"error": "..."} on auth failure
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"Kalshi auth failed: {payload['error']}. Rotate API key at trading.kalshi.com/settings/api-keys")
    expected_keys = {"cursor", "event_positions", "positions", "market_positions"}
    if not isinstance(payload, dict) or not set(payload.keys()) <= expected_keys:
        raise RuntimeError(f"unexpected auth probe response keys: {sorted(payload.keys())}")


def _print_top_opportunities(insights: list[dict], header: str) -> None:
    """Render the top opportunities in a scannable, reviewer-friendly block."""
    logger.info("")
    logger.info(header)
    logger.info("=" * len(header))
    for idx, insight in enumerate(insights[:3], 1):
        market_prob = insight.get("market_prob", 0) * 100
        edge_pct = insight.get("effective_edge_pct", insight.get("edge_pct", 0))
        confidence = insight.get("confidence", 0) * 100
        side = insight.get("side", "YES")
        title = insight.get("title", insight.get("ticker", "?"))
        logger.info(
            "%s. %s",
            idx,
            title[:72],
        )
        logger.info(
            "   %s @ %.0f%% | %.0f%% edge | %.0f%% conf",
            side,
            market_prob,
            edge_pct,
            confidence,
        )
        reasoning = insight.get("reasoning", "")
        if reasoning:
            logger.info("   %s", reasoning[:140])


def _print_no_edges_message(market_count: int) -> None:
    """Explain clearly when the scan found nothing actionable."""
    logger.info("")
    logger.info("NO EDGE MARKETS RIGHT NOW")
    logger.info("=========================")
    logger.info(
        "Checked %s markets and found no opportunities above the live edge/confidence thresholds.",
        market_count,
    )
    logger.info("Check back later — the scanner is working, there just isn't a trade worth forcing.")


# ── API Schema Normalization ────────────────────────────────────────────────
def _normalize_market(m: dict) -> dict:
    """Normalize Kalshi API v3 dollar-string fields to integer cents.

    Kalshi API changed field names (e.g., yes_bid → yes_bid_dollars).
    This helper converts new dollar-string fields to integer cents the rest
    of the code expects. Only normalizes if new fields are present and old ones
    are missing (safe to call on already-normalized dicts).
    """
    def _dollars_to_cents(val):
        """Convert dollar value (float like 0.45 or string '0.4500') to integer cents (45).

        V3 API returns dollar floats (e.g. 0.45 = 45 cents).
        V2 API returned integer cents (e.g. 45). Both handled correctly.
        """
        if val is None:
            return 0
        try:
            fval = float(val)
            # Dollar values from v3 API are < 1.01 (prediction market prices 0-100 cents)
            # Integer cents from v2 API are >= 1 (except sub-penny which rounds to 0)
            if fval <= 1.01:
                return int(round(fval * 100))
            else:
                return int(round(fval))
        except (ValueError, TypeError):
            return 0

    def _fp_to_int(val):
        """Convert float-point string like '1234.00' to integer."""
        if val is None:
            return 0
        if isinstance(val, int):
            return val
        try:
            return int(round(float(val)))
        except (ValueError, TypeError):
            return 0

    # Only normalize if new fields are present and old ones are missing
    if m.get("yes_bid") is None and "yes_bid_dollars" in m:
        m["yes_bid"] = _dollars_to_cents(m.get("yes_bid_dollars"))
        m["yes_ask"] = _dollars_to_cents(m.get("yes_ask_dollars"))
        m["no_bid"] = _dollars_to_cents(m.get("no_bid_dollars"))
        m["no_ask"] = _dollars_to_cents(m.get("no_ask_dollars"))
        m["last_price"] = _dollars_to_cents(m.get("last_price_dollars"))
        m["yes_price"] = m.get("yes_price") or _dollars_to_cents(m.get("yes_bid_dollars"))  # approximate
        m["previous_yes_bid"] = _dollars_to_cents(m.get("previous_yes_bid_dollars"))
        m["previous_yes_ask"] = _dollars_to_cents(m.get("previous_yes_ask_dollars"))
        m["previous_price"] = _dollars_to_cents(m.get("previous_price_dollars"))
        m["volume"] = _fp_to_int(m.get("volume_fp"))
        m["volume_24h"] = _fp_to_int(m.get("volume_24h_fp"))
        m["open_interest"] = _fp_to_int(m.get("open_interest_fp"))
        m["liquidity"] = _dollars_to_cents(m.get("liquidity_dollars"))
        m["notional_value"] = _dollars_to_cents(m.get("notional_value_dollars"))
    return m


# ── Schema Canary ─────────────────────────────────────────────────────────

def _schema_canary(client) -> bool:
    """Pre-flight check: verify Kalshi API returns expected v3 fields.

    Fetches one market and validates schema. Returns True if v3 fields present.
    Logs warning with specific missing fields if schema changed.
    Never blocks the scan — returns True on failure (fail-open).
    """
    EXPECTED_V3 = {
        "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
        "volume_fp", "open_interest_fp", "ticker", "title", "status",
        "close_time", "event_ticker",
    }
    try:
        url = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1&status=open"
        resp = client.call_api("GET", url)
        data = json.loads(resp.read())
        markets = data.get("markets", [])
        if not markets:
            logger.warning("Schema canary: no markets returned")
            return True  # fail-open

        present = set(markets[0].keys())
        missing = EXPECTED_V3 - present
        if missing:
            logger.warning(f"Schema canary: MISSING v3 fields: {missing} — Kalshi may have changed API again")
            return False

        # Check if old v2 fields came back with real values (API revert?)
        m = markets[0]
        v2_revived = [f for f in ("yes_bid", "volume", "last_price") if m.get(f) is not None and m.get(f) != 0]
        if v2_revived:
            logger.info(f"Schema canary: v2 fields have values again: {v2_revived} — normalization may need update")

        logger.info("Schema canary: OK — v3 fields present")
        return True
    except Exception as e:
        logger.warning(f"Schema canary error: {e}")
        return True  # fail-open


# ── Category Filtering ──────────────────────────────────────────────────────

_ALLOWED_CATEGORIES = {
    "politics", "policy", "government", "election", "geopolitics",
    "economics", "macro", "fed", "regulation", "legal", "trade",
    "crypto", "finance", "technology", "ai",
}

_BLOCKED_TICKER_PREFIXES = {
    "KXHIGH", "KXLOW", "KXRAIN", "KXSNOW", "KXTEMP", "KXWIND", "KXWEATH",
    "INX", "NASDAQ", "FED-MR", "KXCELEB", "KXMOVIE", "KXTIKTOK", "KXYT",
    "KXTWIT", "KXSTREAM",
}

_BLOCKED_CATEGORIES_API = {
    "weather", "climate", "entertainment", "sports",
    "social-media", "streaming", "celebrities",
}

# Single words use word-boundary regex; multi-word phrases use substring match.
# This prevents "finals" from matching "Final GDP report" while still catching
# "NBA Finals" or "Stanley Cup Finals".
_SPORTS_WORDS = {
    "nfl", "nba", "mlb", "nhl", "mls", "ncaa", "pga", "ufc", "wwe",
    "wnba", "lpga", "nascar", "f1", "mma",
    "playoff", "playoffs", "heisman",
    "valorant", "atp", "wta", "itf",
    "baseball", "basketball", "football", "hockey", "soccer",
    "tennis", "cricket", "rugby", "boxing", "wrestling",
    "esports", "motorsport",
    # Player prop / match betting terms — added March 15
    "goal", "goals", "goalscorer", "assists", "scorer",
    "halftime", "fulltime", "penalty", "offside",
    "goalkeeper", "touchdowns", "rushing", "receiving",
    "strikeouts", "innings", "rebounds", "sacks",
}

_SPORTS_PHRASES = {
    "super bowl", "superbowl", "march madness", "world series",
    "stanley cup", "nba finals", "nhl finals", "mlb finals",
    "premier league", "la liga", "serie a",
    "bundesliga", "ligue 1", "champions league", "europa league",
    "league of legends", "copa america", "copa del rey",
    "challenger tour", "challenger round",
    "world baseball classic", "indian wells", "grand prix",
    "world cup", "gold cup", "nations league",
    "college baseball", "college basketball", "college football",
    "wins by over", "total runs", "total goals", "total points",
    "first to score", "1+ goals", "2+ goals",
    "moneyline", "spread", "over under",
    # Player prop phrases — added March 15
    "over 0.5 goals", "over 1.5 goals", "over 2.5 goals", "over 3.5 goals",
    "under 0.5 goals", "under 1.5 goals", "under 2.5 goals", "under 3.5 goals",
    "anytime goalscorer", "first goalscorer", "last goalscorer",
    "shots on target", "cards in match", "match result",
    "to score", "to assist", "player props",
}

# Ticker prefixes that are always sports — hard block
_SPORTS_TICKER_PREFIXES = {
    "KXATP", "KXNFL", "KXNBA", "KXMLB", "KXNHL", "KXMLS",
    "KXNCAA", "KXPGA", "KXUFC", "KXWWE", "KXSOCCER", "KXTENNIS",
    "KXWBC", "KXCBB", "KXCFB", "KXWNBA", "KXLPGA", "KXF1",
    "KXNASCAR", "KXCRICKET", "KXRUGBY", "KXBOXING", "KXMMA",
    "KXESPORT", "KXLOL", "KXDOTA", "KXCSK", "KXWTA",
    "KXMVE",  # Kalshi multi-variant event combos (mostly sports) — added March 15
    "KXEPL", "KXUCL", "KXLALIGA", "KXSERIA", "KXBUND", "KXLIG1",
}

_MICRO_TIMEFRAME_PATTERNS = {
    "in next 15 min", "in next 30 min", "in next 1 hour",
    "in next 5 min", "in next 10 min", "next 15 minutes",
    "next 30 minutes", "next hour", "price up in next",
    "price down in next",
}

_POLITICS_NOISE_PATTERNS = {
    "primary", "runoff", "special election", "city council",
    "state senate", "state house", "state rep", "alderman",
    "margin of victory", "vote share", "win by more than",
    "win by less than", "percentage of vote",
    "win between", "win above", "seats in the",
    "leave office next", "leave office first",
    "be 1st in the next", "be first in the next",
    "next presidential election first round",
    "dutch election", "czech election", "argentine election",
    "brazilian election", "mexican election", "colombian election",
    "peruvian election", "chilean election", "turkish election",
    "south korean election", "japanese election", "indian election",
    "australian election", "canadian election",
    "romanian presidential", "japanese house",
    "gorton and denton",
}

_PRICE_THRESHOLD_RE = re.compile(
    r"(price|close|drop|fall|rise|trade|open|hit|reach|touch|break|stay)"
    r"\s+(above|below|over|under|at or above|at or below)"
    r"\s+\$?[\d,]+",
    re.IGNORECASE,
)

_PRICE_ASSET_RE = re.compile(
    r"(bitcoin|btc|ethereum|eth|solana|sol|dogecoin|doge|xrp"
    r"|s&p|s&p 500|nasdaq|dow jones|djia|russell|vix"
    r"|gold|silver|oil|crude|wti|brent|natural gas"
    r"|aapl|amzn|goog|googl|msft|nvda|tsla|meta)"
    r"\s+.{0,20}(above|below|over|under|exceed|less than)\s+\$?[\d,]+",
    re.IGNORECASE,
)

_COINFLIP_PATTERNS = {
    "when will", "how many", "what will be the", "who will the next", "how much will",
}

_IPO_RE = re.compile(r"\bipo\b", re.IGNORECASE)


def _is_noise_market(title: str, price_cents: int = 50) -> str:
    """Return a noise reason for low-signal market prompts, else an empty string."""
    title_lower = title.lower()

    if _PRICE_THRESHOLD_RE.search(title):
        return "price_threshold"
    if _PRICE_ASSET_RE.search(title):
        return "price_asset"
    if any(pattern in title_lower for pattern in _POLITICS_NOISE_PATTERNS):
        return "politics_noise"
    if 40 <= price_cents <= 60:
        if _IPO_RE.search(title):
            return "coinflip_ipo"
        if any(pattern in title_lower for pattern in _COINFLIP_PATTERNS):
            return "coinflip_uncertain"
    return ""


def _is_blocked(ticker: str, category: str = "", title: str = "", price_cents: int = 50) -> bool:
    """Check if a market should be excluded from analysis."""
    ticker_upper = ticker.upper()
    if any(ticker_upper.startswith(prefix) for prefix in _BLOCKED_TICKER_PREFIXES):
        return True
    if category and category.lower().strip() in _BLOCKED_CATEGORIES_API:
        return True
    title_lower = title.lower()
    if any(pat in title_lower for pat in _MICRO_TIMEFRAME_PATTERNS):
        return True
    if _is_noise_market(title, price_cents=price_cents):
        return True
    return False


def _is_sports(ticker: str, title: str) -> bool:
    """Detect sports markets using word-boundary matching.

    Three-layer check:
      1. Ticker prefix (KXATP*, KXNFL*, etc.) — always sports
      2. Single-word tokens with word boundaries — "finals" won't match "Final GDP"
      3. Multi-word phrases with substring match — "stanley cup" is unambiguous
    """
    ticker_upper = ticker.upper()
    if any(ticker_upper.startswith(p) for p in _SPORTS_TICKER_PREFIXES):
        return True

    combined = f"{ticker} {title}".lower()

    # Word-boundary match for single tokens
    for word in _SPORTS_WORDS:
        if re.search(rf'\b{re.escape(word)}\b', combined):
            return True

    # Substring match for multi-word phrases (unambiguous)
    for phrase in _SPORTS_PHRASES:
        if phrase in combined:
            return True

    return False


# ── Phase 1: Market Fetching ──────────────────────────────────────────────

_EVENTS_TARGET_CATS = {
    "Politics", "Economics", "Science and Technology", "World",
    "Companies", "Elections", "Financials", "Health", "Transportation", "Social",
}


def _fetch_via_events(client, cfg: dict, max_fetch_seconds: float = 45) -> list[dict]:
    """Fetch markets through the /events endpoint (v3 primary strategy).

    Events-based fetching skips the sports combo flood and gives us
    categorized data. Returns normalized market dicts with event category.
    """
    base = "https://api.elections.kalshi.com/trade-api/v2"
    all_markets = []
    fetch_start = time.time()

    # Paginate events
    all_events = []
    cursor = None
    for _ in range(5):
        url = f"{base}/events?limit=200&status=open"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            resp = client.call_api("GET", url)
            data = json.loads(resp.read())
        except Exception as e:
            logger.error(f"Events fetch error: {e}")
            break
        evts = data.get("events", [])
        if not evts:
            break
        all_events.extend(evts)
        cursor = data.get("cursor")
        if not cursor:
            break

    target = [e for e in all_events if e.get("category") in _EVENTS_TARGET_CATS]
    logger.info(f"Events fetch: {len(all_events)} total → {len(target)} in target categories")

    # Fetch markets per target event
    for evt in target:
        if time.time() - fetch_start > max_fetch_seconds:
            logger.info(f"Events fetch: hit {max_fetch_seconds}s budget after {len(all_markets)} markets")
            break
        et = evt.get("event_ticker", "")
        if not et:
            continue
        try:
            resp = client.call_api("GET", f"{base}/events/{et}")
            data = json.loads(resp.read())
            mkts = data.get("markets", [])
            for m in mkts:
                # Only active/open markets
                if m.get("status") not in ("active", "open"):
                    continue
                # Skip KXMVE combo markets
                if m.get("ticker", "").startswith("KXMVE"):
                    continue
                m = _normalize_market(m)
                # Attach event category (v3 market.category is often None)
                m["category"] = evt.get("category", "").lower()
                all_markets.append(m)
        except Exception:
            continue

    logger.info(f"Events fetch: {len(all_markets)} markets from {len(target)} events")
    return all_markets


def fetch_kalshi_markets(client, cfg: dict) -> list[dict]:
    """Fetch and pre-filter Kalshi markets.

    Primary strategy: events-based fetch (skips sports combo flood).
    Fallback: direct /markets pagination if events returns < 20 markets.

    Args:
        client: Initialized Kalshi client
        cfg: Configuration dict with fetch parameters

    Returns:
        List of pre-filtered market dicts
    """
    min_volume = cfg.get("min_volume", 50)
    min_days = cfg.get("min_days_to_close", 7)
    max_days = cfg.get("max_days_to_close", 365)
    max_pages = cfg.get("max_pages", 10)
    fresh_mode = cfg.get("fresh_mode", False)
    max_age_hours = cfg.get("fresh_max_age_hours", 48)

    if fresh_mode:
        min_volume = 0
        min_days = 2
        logger.info(
            f"FRESH MODE: relaxed filters (min_vol=0, min_days=2, max_age={max_age_hours}h)"
        )

    max_fetch_seconds = cfg.get("max_fetch_seconds", 45)

    # ── Run schema canary ──
    _schema_canary(client)

    # ── Primary: events-based fetch ──
    all_markets = _fetch_via_events(client, cfg, max_fetch_seconds=max_fetch_seconds)

    # ── Fallback: direct /markets pagination ──
    if len(all_markets) < 20:
        logger.info(f"Events fetch returned only {len(all_markets)} markets, falling back to /markets pagination")
        all_markets = []
        cursor = None
        fetch_start = time.time()

        for page in range(max_pages):
            if time.time() - fetch_start > max_fetch_seconds:
                logger.info(f"Fetch: hit {max_fetch_seconds}s budget at page {page}")
                break

            try:
                url = (
                    "https://api.elections.kalshi.com/trade-api/v2/markets"
                    "?limit=200&status=open&mve_filter=exclude"
                )
                if cursor:
                    url += f"&cursor={cursor}"

                resp = client.call_api("GET", url)
                data = json.loads(resp.read())

                markets = [_normalize_market(m) for m in data.get("markets", [])]
                all_markets.extend(markets)
                cursor = data.get("cursor")

                if not cursor or not markets:
                    break

                logger.info(f"Fetch: page {page}, got {len(markets)} markets")

            except Exception as e:
                logger.error(f"Fetch error at page {page}: {e}")
                break

    logger.info(f"Fetch: {len(all_markets)} raw markets")

    # Pre-filter
    filtered = []
    stats = {
        "no_book": 0,
        "blocked": 0,
        "sports": 0,
        "volume": 0,
        "timeframe": 0,
        "stale": 0,
    }

    for m in all_markets:
        ticker = m.get("ticker", "")
        title = m.get("title", "")
        category = m.get("category", "") or m.get("series_ticker", "")
        volume = m.get("volume", 0) or 0
        yes_bid = m.get("yes_bid", 0) or 0
        yes_ask = m.get("yes_ask", 0) or 0
        yes_price = m.get("yes_price", 0) or 0
        last_price = m.get("last_price", 0) or 0

        # Resolve price
        if yes_bid and yes_ask:
            price = int((yes_bid + yes_ask) / 2)
            spread = yes_ask - yes_bid
        elif yes_price:
            price = yes_price
            spread = 2
        elif last_price:
            price = last_price
            spread = 2
        else:
            stats["no_book"] += 1
            continue

        if price <= 0 or price >= 100:
            stats["no_book"] += 1
            continue

        if _is_blocked(ticker, category, title, price_cents=price):
            stats["blocked"] += 1
            continue

        if volume < min_volume:
            stats["volume"] += 1
            continue

        is_sports = _is_sports(ticker, title)
        if is_sports:
            stats["sports"] += 1
            continue  # HARD BLOCK: never pass sports markets downstream

        days_to_close = _calc_days_to_close(m)
        if days_to_close is None or days_to_close < min_days or days_to_close > max_days:
            stats["timeframe"] += 1
            continue

        market_age_hours = _calc_market_age_hours(m)
        if fresh_mode and (market_age_hours is None or market_age_hours > max_age_hours):
            stats["stale"] += 1
            continue

        filtered.append({
            "ticker": ticker,
            "title": title[:80],
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "yes_price": price,
            "spread": spread,
            "volume": volume,
            "open_interest": m.get("open_interest", 0) or 0,
            "days_to_close": days_to_close,
            "market_age_hours": market_age_hours,
            "expiration_time": m.get("expiration_time", ""),
            "is_sports": is_sports,
        })

    logger.info(
        f"Fetch: {len(filtered)} passed filters (blocked={stats['blocked']}, "
        f"sports_tagged={stats['sports']}, volume={stats['volume']}, "
        f"timeframe={stats['timeframe']}, stale={stats['stale']})"
    )
    return filtered


def _calc_days_to_close(m: dict) -> Optional[float]:
    """Calculate days until market closes."""
    expiration = m.get("expiration_time") or m.get("close_time", "")
    if not expiration or not isinstance(expiration, str):
        return None
    try:
        exp_str = expiration.replace("Z", "+00:00")
        exp_dt = datetime.fromisoformat(exp_str)
        return max(0, (exp_dt - datetime.now(timezone.utc)).total_seconds() / 86400)
    except (ValueError, TypeError):
        return None


def _calc_market_age_hours(m: dict) -> Optional[float]:
    """Calculate hours since market opened for trading."""
    open_time = m.get("open_time", "")
    if not open_time or not isinstance(open_time, str):
        return None
    try:
        open_str = open_time.replace("Z", "+00:00")
        open_dt = datetime.fromisoformat(open_str)
        age_hours = (datetime.now(timezone.utc) - open_dt).total_seconds() / 3600
        return max(0, age_hours)
    except (ValueError, TypeError):
        return None


# ── Phase 3: Claude Estimation ────────────────────────────────────────────

def estimate_with_claude(
    market_title: str,
    market_price_cents: int,
    days_to_close: Optional[float],
    news: Optional[list[dict]] = None,
    economic_context: Optional[dict] = None,
    x_signal: Optional[dict] = None,
) -> Optional[dict]:
    """Estimate probability using Claude Sonnet (contrarian mode).

    Claude sees the market price and is asked to find reasons it's WRONG.
    Falls back to Qwen if Claude is unavailable.
    """
    from claude_estimator import estimate_probability

    return estimate_probability(
        market_title=market_title,
        days_to_close=days_to_close,
        news_context=news,
        economic_context=economic_context,
        x_signal=x_signal,
        market_price_cents=market_price_cents,
    )


def calculate_edges(markets: list[dict], cfg: dict) -> list[dict]:
    """Phase 3+4: Claude estimation + edge calculation."""
    from claude_estimator import estimate_batch

    max_to_analyze = cfg.get("max_markets_to_analyze", 50)

    # Sort by priority
    def _priority_score(m: dict) -> float:
        mid = m.get("yes_price", 50)
        oi = m.get("open_interest", 0)
        centrality = 1 - abs(mid - 50) / 50
        return centrality * (oi ** 0.3) * (m.get("volume", 0) ** 0.2)

    markets.sort(key=_priority_score, reverse=True)
    candidates = markets[:max_to_analyze]

    logger.info(f"Edge: analyzing {len(candidates)} markets with Claude")

    # Run Claude batch
    results = estimate_batch(candidates, economic_context=None, max_markets=max_to_analyze)

    # Filter by minimum edge
    min_edge = cfg.get("min_edge_pct", 3.0)
    edges = [r for r in results if r.get("effective_edge_pct", 0) >= min_edge]

    edges.sort(key=lambda x: x.get("effective_edge_pct", 0), reverse=True)
    logger.info(f"Edge: {len(edges)} with >= {min_edge}% effective edge")

    return edges


# ── Phase 4.5: Post-estimation Market Filter ────────────────────────────────

def _apply_market_filter(edges: list[dict], cfg: dict) -> list[dict]:
    """Post-estimation filter: remove low-quality edges before execution.

    Applied AFTER Claude estimation, so we can filter on estimated values
    like confidence, edge size, and direction — not just raw market data.

    Implements three filter phases:
      Phase A: Simple quality checks (edge/confidence/spread)
      Phase B: Category skip rules (fed, sports, esports, price/timeframe thresholds)
      Phase C: Boost rules (policy/tech/markets, Goldilocks price, strong edge, long horizon)

    For each edge that passes all phases:
      - Set market_filter_action = "pass"
      - Set boost_multiplier (1.0 to max_boost_multiplier)

    For each edge that fails:
      - Set market_filter_action = "skip"
      - Set market_filter_reason (e.g., "category_fed", "price_too_low", etc.)

    auto_trader.py checks these fields to skip edges before execution.
    """
    # ── Phase A: Simple quality checks (existing logic) ──
    min_edge = cfg.get("min_edge_pct", 3.0)
    min_conf = cfg.get("min_confidence", 0.2)
    exclude_fair = cfg.get("exclude_fair_direction", True)
    max_spread = cfg.get("max_spread_cents", 10)
    if cfg.get("fresh_mode", False):
        max_spread = 25

    before = len(edges)
    filtered = []
    stats = {
        "low_edge": 0,
        "low_conf": 0,
        "fair": 0,
        "wide_spread": 0,
        "category_skip": 0,
        "price_too_low": 0,
        "days_too_short": 0,
        "days_too_long": 0,
        "boosted": 0,
    }

    mf_cfg = _MARKET_FILTER_CFG or {}
    skip_rules = mf_cfg.get("skip_rules", {})
    boost_rules = mf_cfg.get("boost_rules", {})
    max_boost = mf_cfg.get("max_boost_multiplier", 1.50)

    skip_categories = skip_rules.get("categories", ["fed", "sports", "esports"])
    max_price = skip_rules.get("max_price_cents", 20)
    min_days = skip_rules.get("min_days_to_close", 5)
    other_max_days = skip_rules.get("other_category_max_days", 10)

    boost_categories = boost_rules.get("high_edge_categories", ["policy", "technology", "markets"])
    boost_cat_mult = boost_rules.get("high_edge_category_multiplier", 1.25)
    goldilocks_min = boost_rules.get("goldilocks_price_min_cents", 66)
    goldilocks_mult = boost_rules.get("goldilocks_price_multiplier", 1.20)
    strong_edge_thresh = boost_rules.get("strong_edge_threshold", 0.30)
    strong_edge_mult = boost_rules.get("strong_edge_multiplier", 1.15)
    long_horizon_min = boost_rules.get("long_horizon_min_days", 30)
    long_horizon_mult = boost_rules.get("long_horizon_multiplier", 1.10)

    for e in edges:
        ticker = e.get("ticker", "?")
        eff_edge = e.get("effective_edge_pct", 0)
        conf = e.get("confidence", 0)
        direction = e.get("direction", "fair")
        spread = e.get("spread", 0)
        category = (e.get("category", "") or "").lower().strip()
        yes_price = e.get("yes_price", 50)
        days_to_close = e.get("days_to_close", 0) or 0

        if eff_edge < min_edge:
            stats["low_edge"] += 1
            e["market_filter_action"] = "skip"
            e["market_filter_reason"] = "low_edge"
            continue

        if conf < min_conf:
            stats["low_conf"] += 1
            e["market_filter_action"] = "skip"
            e["market_filter_reason"] = "low_confidence"
            continue

        if exclude_fair and direction == "fair":
            stats["fair"] += 1
            e["market_filter_action"] = "skip"
            e["market_filter_reason"] = "fair_direction"
            continue

        if max_spread and spread > max_spread:
            stats["wide_spread"] += 1
            e["market_filter_action"] = "skip"
            e["market_filter_reason"] = "wide_spread"
            continue

        skip_reason = None

        if category in skip_categories:
            stats["category_skip"] += 1
            skip_reason = f"category_{category}"

        if yes_price < max_price and skip_reason is None:
            stats["price_too_low"] += 1
            skip_reason = "price_too_low"

        if skip_reason is None:
            if category in boost_categories:
                if days_to_close < min_days:
                    stats["days_too_short"] += 1
                    skip_reason = "days_too_short"
            else:
                if days_to_close < other_max_days:
                    stats["days_too_long"] += 1
                    skip_reason = "days_too_short_other"

        if skip_reason:
            e["market_filter_action"] = "skip"
            e["market_filter_reason"] = skip_reason
            logger.debug("MarketFilter: skip %s (%s)", ticker, skip_reason)
            continue

        boost = 1.0

        if category in boost_categories:
            boost *= boost_cat_mult

        if goldilocks_min <= yes_price <= 90:
            boost *= goldilocks_mult

        if eff_edge >= strong_edge_thresh:
            boost *= strong_edge_mult

        if days_to_close >= long_horizon_min:
            boost *= long_horizon_mult

        boost = min(boost, max_boost)

        e["market_filter_action"] = "pass"
        e["market_filter_reason"] = ""
        e["boost_multiplier"] = round(boost, 4)
        if boost > 1.0:
            stats["boosted"] += 1

        filtered.append(e)

    # Sort by effective edge descending
    filtered.sort(key=lambda x: x.get("effective_edge_pct", 0), reverse=True)

    logger.info(
        f"MarketFilter: {before} → {len(filtered)} edges "
        f"(quality: low_edge={stats['low_edge']}, low_conf={stats['low_conf']}, "
        f"fair={stats['fair']}, wide_spread={stats['wide_spread']} | "
        f"category: skip={stats['category_skip']}, price={stats['price_too_low']}, "
        f"days_short={stats['days_too_short']}, days_long={stats['days_too_long']} | "
        f"boosted={stats['boosted']})"
    )
    return filtered


def format_insight(edge: dict) -> dict:
    """Format edge result for output."""
    est = edge.get("estimated_probability", 0.5)
    mkt = edge.get("market_implied", 0.5)
    direction = edge.get("direction", "fair")

    return {
        "ticker": edge.get("ticker", "?"),
        "title": edge.get("title", "?")[:60],
        "side": "YES" if direction == "underpriced" else "NO",
        "confidence": "high" if edge.get("confidence", 0) > 0.6 else "medium",
        "yes_bid": edge.get("yes_bid", 0),
        "yes_ask": edge.get("yes_ask", 0),
        "volume": edge.get("volume", 0),
        "open_interest": edge.get("open_interest", 0),
        "days_to_close": edge.get("days_to_close"),
        "market_age_hours": edge.get("market_age_hours"),
        "is_fresh": (edge.get("market_age_hours") or 999) <= 48,
        "market_prob": round(mkt, 4),
        "estimated_prob": round(est, 4),
        "edge_pct": edge.get("edge_pct", 0),
        "effective_edge_pct": edge.get("effective_edge_pct", 0),
        "direction": direction,
        "reasoning": edge.get("reasoning", ""),
        "estimator": edge.get("estimator", "unknown"),
    }


def run_kalshalyst(client, cfg: dict, dry_run: bool = False) -> bool:
    """Main Kalshalyst pipeline."""
    logger.info("=" * 60)
    logger.info("Kalshalyst starting (Claude contrarian estimation)...")
    logger.info("=" * 60)

    # Phase 1: Fetch
    markets = fetch_kalshi_markets(client, cfg)
    if not markets:
        _write_fail_loud_cache(
            "no_markets_after_fetch",
            known=f"trade ledger still tracks {_ledger_context().get('ledger_open_positions', 0)} open positions",
        )
        if cfg.get("fresh_mode", False):
            logger.info("I don't know if there are fresh opportunities — no new markets passed the relaxed fetch window")
        else:
            logger.info("I don't know current opportunities — no markets passed fetch filters")
        return False

    # Phase 3+4: Estimate + edge
    edges = calculate_edges(markets, cfg)
    edges = _apply_market_filter(edges, cfg)

    # Preserve original edge metrics for downstream Kelly sizing when a filter boost applies.
    for e in edges:
        if e.get("market_filter_action") == "pass" and e.get("boost_multiplier", 1.0) > 1.0:
            e["original_edge_pct"] = e.get("edge_pct", 0)
            e["original_effective_edge_pct"] = e.get("effective_edge_pct", 0)
    if not edges:
        _write_fail_loud_cache(
            "no_confirmed_edges",
            known=f"Kalshalyst scanned {len(markets)} markets but did not produce confirmed opportunities",
        )
        _print_no_edges_message(len(markets))
        return True

    # Phase 5: Cache + alert
    cache_payload = {
        "insights": [format_insight(e) for e in edges[:20]],
        "macro_count": len(edges),
        "total_scanned": len(markets),
        "scanner_version": "1.0.0",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        **_ledger_context(),
    }

    logger.info(f"Kalshalyst: {len(edges)} opportunities found")

    # Phase 5: Write cache for morning-brief consumption
    try:
        _write_cache(cache_payload)
        logger.info("Cache written to %s", Path.home() / ".openclaw" / "state" / "kalshalyst_cache.json")
    except OSError as e:
        logger.warning(f"Could not write cache: {e}")

    if dry_run:
        logger.info("[DRY RUN] Would send alerts")
        _print_top_opportunities(cache_payload["insights"], "TOP 3 EDGE OPPORTUNITIES")
        return True

    # Alert on high-edge opportunities
    alert_threshold = cfg.get("alert_edge_pct", 6.0)
    alert_candidates = [e for e in edges if e.get("effective_edge_pct", 0) >= alert_threshold]

    if alert_candidates:
        logger.info(f"Kalshalyst: {len(alert_candidates)} above alert threshold ({alert_threshold}%)")
        _print_top_opportunities(cache_payload["insights"], "TOP 3 EDGE OPPORTUNITIES")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kalshalyst")
    parser.add_argument("--dry-run", action="store_true", help="Don't send alerts")
    parser.add_argument("--force", action="store_true", help="Force run (ignore interval)")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Scan only markets listed in last 48h with relaxed filters",
    )

    args = parser.parse_args()
    cfg = {}
    if args.fresh:
        cfg["fresh_mode"] = True

    # ── Load config from ~/.openclaw/config.yaml ──
    yaml = None
    try:
        import yaml as _yaml
        yaml = _yaml
    except ImportError:
        logger.warning("pyyaml not installed — continuing with demo-friendly defaults.")

    config_path = Path.home() / ".openclaw" / "config.yaml"
    file_config = {}
    if config_path.exists() and yaml:
        with open(config_path) as f:
            file_config = yaml.safe_load(f) or {}

    kalshi_cfg = file_config.get("kalshi", {})
    key_id = kalshi_cfg.get("api_key_id", "")
    pk_file = kalshi_cfg.get("private_key_file", "")
    pk_path = Path(pk_file).expanduser()
    if not pk_path.is_absolute():
        pk_path = Path.home() / ".openclaw" / "keys" / pk_path

    if not key_id or not pk_path.exists():
        logger.warning(
            "Kalshi credentials missing — showing demo scan so you can preview the output before setup."
        )
        _show_demo_scan("Demo only: add Kalshi credentials in ~/.openclaw/config.yaml to run the live scanner.")
        sys.exit(0)

    # ── Initialize Kalshi SDK client ──
    try:
        try:
            from kalshi_python_sync import Configuration, KalshiClient
        except ImportError:
            from kalshi_python import Configuration, KalshiClient

        base_url = "https://api.elections.kalshi.com/trade-api/v2"
        sdk_config = Configuration(host=base_url)
        with open(pk_path, "r") as f:
            sdk_config.private_key_pem = f.read().strip()
        sdk_config.api_key_id = key_id
        client = KalshiClient(sdk_config)
        sdk_config.private_key_pem = None  # clear PEM from memory

        _verify_kalshi_client(client)
        logger.info("Kalshi client initialized successfully")
    except Exception as e:
        logger.warning(
            "Kalshi client init failed — showing demo scan instead: %s",
            str(e).splitlines()[0],
        )
        _show_demo_scan("Demo only: fix Kalshi auth/init to run the live scanner.")
        sys.exit(0)

    # ── Run pipeline ──
    if args.force:
        cfg["force"] = True
    success = run_kalshalyst(client, cfg, dry_run=args.dry_run)
    sys.exit(0 if success else 1)
