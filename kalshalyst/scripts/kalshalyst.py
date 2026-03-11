"""Kalshalyst — Claude-powered contrarian estimation.

Pipeline:
  Phase 1: FETCH — Kalshi markets with blocklist + timeframe filtering
  Phase 2: CLASSIFY — Disabled (Qwen unreliable). Markets pass through with defaults.
  Phase 3: ESTIMATE — Claude Sonnet contrarian estimation (sees price, finds disagreements)
  Phase 4: EDGE — Raw edge calculation (limit order assumption, no spread penalty)
  Phase 5: CACHE + ALERT — Write cache, alert on high-edge opportunities
  Phase 6: AUTO-EXECUTE — If auto_trader_config.json enabled, execute via Kelly + Kalshi API

Key change from prior versions: Claude now sees the market price and is prompted to find
reasons the market is wrong. Blind estimation produced consensus-matching
estimates with zero edge. Contrarian mode produces opinionated directional calls.
Falls back to Qwen if Claude is unavailable (offline/cooldown).

Usage:
    python kalshalyst.py [--dry-run] [--force]
"""

import json
import re
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


# ── Ensemble Configuration ──────────────────────────────────────────────────
# Load ensemble weights for signal combination
def _load_ensemble_weights(cfg: dict) -> Optional[dict]:
    """Load ensemble weights from config path. Returns None if disabled or missing."""
    if not cfg.get("ensemble_enabled", False):
        return None

    weights_path = cfg.get("ensemble_weights_path", "")
    if not weights_path:
        logger.debug("Ensemble enabled but no weights_path configured")
        return None

    try:
        weights_file = Path(weights_path)
        if not weights_file.exists():
            logger.warning(f"Ensemble weights file not found: {weights_path}")
            return None

        with open(weights_file) as f:
            weights = json.load(f)

        # Validate structure
        required_keys = {"w_kalshalyst", "w_xpulse", "w_market"}
        if not all(k in weights for k in required_keys):
            logger.error(f"Ensemble weights missing keys. Required: {required_keys}")
            return None

        # Validate weights sum to 1.0 (within tolerance)
        total = weights["w_kalshalyst"] + weights["w_xpulse"] + weights["w_market"]
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Ensemble weights sum to {total:.3f}, not 1.0 — normalizing")
            weights["w_kalshalyst"] /= total
            weights["w_xpulse"] /= total
            weights["w_market"] /= total

        logger.info(f"Ensemble weights loaded: kalshalyst={weights['w_kalshalyst']:.3f}, "
                   f"xpulse={weights['w_xpulse']:.3f}, market={weights['w_market']:.3f}")
        return weights

    except Exception as e:
        logger.error(f"Failed to load ensemble weights from {weights_path}: {e}")
        return None


# ── Category Filtering ──────────────────────────────────────────────────────
# Signal-quality gate based on 165-market eval (backtest_signal_v2.json):
#   STRONG: Technology (0.074 Brier), Policy (0.083), Fed (0.119)
#   OK:     Economics (0.173), Crypto-regulatory (0.151)
#   WEAK:   Politics/elections (0.226), Markets/price-thresholds (0.334)
# Strategy: block patterns where model has NO information advantage.

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

# Long/multi-word tokens safe for simple substring matching
_SPORTS_TOKENS_SUBSTR = {
    "super bowl", "superbowl", "march madness", "world series",
    "stanley cup", "finals game", "playoff", "mvp award", "heisman",
    "premier league", "la liga", "serie a", "bundesliga", "ligue 1",
    "champions league", "europa league", "copa america",
    "challenger", "tennis",
    "valorant", "league of legends", "counter-strike",
    "esports", "esport",
    "boxing", "bellator", "fight night",
    "formula 1", "f1 grand prix", "motogp", "nascar", "cricket",
    # Kalshi sports ticker prefixes (unambiguous compound strings)
    "kxatp", "kxwta", "kxnba", "kxnfl", "kxmlb", "kxnhl", "kxncaa",
    "kxmma", "kxufc", "kxbox", "kxnascar", "kxf1", "kxlol", "kxvalorant",
    "kxcsgo", "kxdota", "kxcricket", "kxipl", "kxtennis",
    # Kalshi match/game/spread ticker patterns
    "challengermatch", "nbaspread", "nflspread", "mlbgame", "nhlgame",
    "nbagame", "nflgame", "lolgame", "ncaambgame", "ncaafbgame",
}

# Short tokens (3-4 chars) that collide with normal words — require word boundary
# "nfl" hits "inflation", "mma" hits "commander", "mlb" hits "assemblb...", etc.
import re as _re
_SPORTS_TOKENS_WORD_BOUNDARY = _re.compile(
    r'\b(?:nfl|nba|mlb|nhl|mls|ncaa|pga|ufc|wwe|atp|wta|itf|mma|lpga|ipl'
    r'|csgo|cs2|dota)\b', _re.IGNORECASE
)

_MICRO_TIMEFRAME_PATTERNS = {
    "in next 15 min", "in next 30 min", "in next 1 hour",
    "in next 5 min", "in next 10 min", "next 15 minutes",
    "next 30 minutes", "next hour", "price up in next",
    "price down in next",
}

# ── Signal-Quality Filters (eval-driven) ─────────────────────────────────
# These patterns identify markets where the LLM has zero information edge.
# Based on category Brier analysis: politics 0.226, markets 0.334.

# Obscure elections — model says 0.53 on everything (no information advantage)
_POLITICS_NOISE_PATTERNS = {
    # Obscure local elections
    "primary", "runoff", "special election", "city council",
    "state senate", "state house", "state rep", "alderman",
    # Margin/seat count multi-choice spam (model says 0.53 on all buckets)
    "margin of victory", "vote share", "win by more than",
    "win by less than", "percentage of vote",
    "win between", "win above", "seats in the",
    # "Leave office" / "who's next" — pure coin-flips at 50¢
    "leave office next", "leave office first",
    # Foreign election first-round predictions
    "be 1st in the next", "be first in the next",
    "next presidential election first round",
    # Foreign elections the model can't predict
    "dutch election", "czech election", "argentine election",
    "brazilian election", "mexican election", "colombian election",
    "peruvian election", "chilean election", "turkish election",
    "south korean election", "japanese election", "indian election",
    "australian election", "canadian election",
    "romanian presidential", "japanese house",
    "gorton and denton",  # UK by-elections
}

# Price threshold markets — need quant model, not LLM reasoning
# e.g. "Will Bitcoin drop below $50k?" "Will S&P 500 close above 5000?"
_PRICE_THRESHOLD_RE = re.compile(
    r'(price|close|drop|fall|rise|trade|open|hit|reach|touch|break|stay)'
    r'\s+(above|below|over|under|at or above|at or below)'
    r'\s+\$?[\d,]+',
    re.IGNORECASE
)

# Additional price patterns: "Will X be above/below Y"
_PRICE_ASSET_RE = re.compile(
    r'(bitcoin|btc|ethereum|eth|solana|sol|dogecoin|doge|xrp'
    r'|s&p|s&p 500|nasdaq|dow jones|djia|russell|vix'
    r'|gold|silver|oil|crude|wti|brent|natural gas'
    r'|aapl|amzn|goog|googl|msft|nvda|tsla|meta)'
    r'\s+.{0,20}(above|below|over|under|exceed|less than)\s+\$?[\d,]+',
    re.IGNORECASE
)

# Coin-flip noise: IPO timing, "when will", "how many" at midrange prices
_COINFLIP_PATTERNS = {
    "when will", "how many", "what will be the",
    "who will the next", "how much will",
}

_IPO_PATTERN = re.compile(r'\bipo\b', re.IGNORECASE)


# ── Eval-Driven Market Filter ─────────────────────────────────────────────
# Post-estimation filter based on Opus eval data (82 markets).
# SKIP = don't trade. BOOST = increase confidence multiplier for Kelly sizing.
# Config lives at ~/prompt-lab/market_filter.json.

def _load_market_filter() -> dict:
    """Load eval-driven market filter config.

    Checks ~/prompt-lab/market_filter.json. Returns empty dict if missing.
    """
    filter_paths = [
        Path.home() / "prompt-lab" / "market_filter.json",
    ]
    for path in filter_paths:
        try:
            if path.exists():
                cfg = json.loads(path.read_text())
                logger.info(f"Market filter loaded from {path} (mode={cfg.get('filter_mode', 'off')})")
                return cfg
        except Exception as e:
            logger.debug(f"Could not load market filter from {path}: {e}")
    return {}

_MARKET_FILTER = _load_market_filter()


def _apply_market_filter(edges: list[dict], cfg: dict) -> list[dict]:
    """Apply eval-driven SKIP and BOOST rules to post-estimation edges.

    SKIP rules remove markets entirely. BOOST rules increase the confidence
    field, which feeds into Kelly sizing for larger positions on high-edge markets.

    Args:
        edges: List of edge dicts from calculate_edges()
        cfg: Kalshalyst config dict (may contain category info)

    Returns:
        Filtered list with boosted confidence values
    """
    mf = _MARKET_FILTER
    if not mf or mf.get("filter_mode") == "off":
        return edges

    skip_rules = mf.get("skip_rules", {})
    boost_rules = mf.get("boost_rules", {})
    max_boost = mf.get("max_boost_multiplier", 1.50)

    skip_categories = set(c.lower() for c in skip_rules.get("categories", []))
    skip_max_price = skip_rules.get("max_price_cents", 0)
    skip_min_days = skip_rules.get("min_days_to_close", 0)
    other_max_days = skip_rules.get("other_category_max_days", 0)

    boost_categories = set(c.lower() for c in boost_rules.get("high_edge_categories", []))
    boost_cat_mult = boost_rules.get("high_edge_category_multiplier", 1.0)
    goldilocks_min = boost_rules.get("goldilocks_price_min_cents", 100)
    goldilocks_mult = boost_rules.get("goldilocks_price_multiplier", 1.0)
    strong_edge_thresh = boost_rules.get("strong_edge_threshold", 1.0)
    strong_edge_mult = boost_rules.get("strong_edge_multiplier", 1.0)
    long_horizon_days = boost_rules.get("long_horizon_min_days", 999)
    long_horizon_mult = boost_rules.get("long_horizon_multiplier", 1.0)

    filtered = []
    skip_count = 0
    boost_count = 0

    for e in edges:
        ticker = e.get("ticker", "").lower()
        title = e.get("title", "").lower()
        price = e.get("yes_price", 50)
        days = e.get("days_to_close") or 999
        edge_abs = abs(e.get("estimated_probability", 0.5) - e.get("market_implied", 0.5))

        # Infer category from ticker/title (Kalshi tickers often encode category)
        category = _infer_category(ticker, title)

        # ── SKIP rules ──
        skip = False

        # Skip: category in skip list (e.g., "fed")
        if category in skip_categories:
            logger.debug(f"Filter SKIP (category={category}): {e.get('title', '?')[:50]}")
            skip = True

        # Skip: ultra-low price
        if not skip and skip_max_price > 0 and price <= skip_max_price:
            logger.debug(f"Filter SKIP (price={price}¢): {e.get('title', '?')[:50]}")
            skip = True

        # Skip: too short time horizon
        if not skip and skip_min_days > 0 and days < skip_min_days:
            logger.debug(f"Filter SKIP (days={days:.0f}): {e.get('title', '?')[:50]}")
            skip = True

        # Skip: "other" category + short duration
        if not skip and category == "other" and other_max_days > 0 and days <= other_max_days:
            logger.debug(f"Filter SKIP (other+short): {e.get('title', '?')[:50]}")
            skip = True

        if skip:
            skip_count += 1
            continue

        # ── BOOST rules (stack multiplicatively, capped) ──
        multiplier = 1.0

        if category in boost_categories:
            multiplier *= boost_cat_mult

        if price >= goldilocks_min:
            multiplier *= goldilocks_mult

        if edge_abs >= strong_edge_thresh:
            multiplier *= strong_edge_mult

        if days >= long_horizon_days:
            multiplier *= long_horizon_mult

        # Cap the total multiplier
        multiplier = min(multiplier, max_boost)

        if multiplier > 1.0:
            original_conf = e.get("confidence", 0.3)
            boosted_conf = min(1.0, original_conf * multiplier)
            e["confidence"] = round(boosted_conf, 4)
            e["filter_boost"] = round(multiplier, 3)
            boost_count += 1
            logger.debug(
                f"Filter BOOST (x{multiplier:.2f}, cat={category}): "
                f"conf {original_conf:.3f} → {boosted_conf:.3f} | {e.get('title', '?')[:50]}"
            )

        filtered.append(e)

    logger.info(
        f"Market filter: {skip_count} skipped, {boost_count} boosted, "
        f"{len(filtered)} passed (from {len(edges)})"
    )
    return filtered


def _infer_category(ticker: str, title: str) -> str:
    """Infer market category from ticker prefix and title keywords.

    Kalshi tickers often encode the category (e.g., FED-*, KXPOL-*).
    Falls back to title keyword matching.
    """
    ticker_upper = ticker.upper()

    # Ticker-based inference
    if ticker_upper.startswith("FED") or "FED-" in ticker_upper:
        return "fed"
    if any(ticker_upper.startswith(p) for p in ("KXPOL", "PRES", "ELECT")):
        return "politics"
    if any(ticker_upper.startswith(p) for p in ("KXTECH", "AI-", "KXAI")):
        return "technology"
    if any(ticker_upper.startswith(p) for p in ("KXCRYPTO", "BTC", "ETH", "KXBTC")):
        return "crypto"
    if any(ticker_upper.startswith(p) for p in ("KXECON", "GDP", "CPI", "JOBS")):
        return "economics"

    # Sports detection (must be before title-based to catch "will X win" patterns)
    if _is_sports(ticker, title):
        return "sports"

    # Title-based inference
    title_lower = title.lower()
    if any(w in title_lower for w in ("federal reserve", "fed funds", "fomc", "rate cut", "rate hike")):
        return "fed"
    if any(w in title_lower for w in ("tariff", "executive order", "regulation", "legislation", "bill pass")):
        return "policy"
    if any(w in title_lower for w in ("ai ", "artificial intelligence", "openai", "google ai", "tech company")):
        return "technology"
    if any(w in title_lower for w in ("s&p", "nasdaq", "dow", "stock market", "index")):
        return "markets"
    if any(w in title_lower for w in ("election", "president", "governor", "senate", "congress", "poll")):
        return "politics"
    if any(w in title_lower for w in ("bitcoin", "ethereum", "crypto", "token", "blockchain")):
        return "crypto"
    if any(w in title_lower for w in ("gdp", "inflation", "unemployment", "jobs report", "cpi")):
        return "economics"
    if any(w in title_lower for w in ("war", "invasion", "nato", "sanction", "missile", "nuclear")):
        return "geopolitics"

    return "other"


def _is_noise_market(title: str, price_cents: int = 50) -> str:
    """Check if a market is a no-edge noise pattern.

    Returns empty string if clean, or a reason string if noise.
    Used for logging/stats — caller decides whether to block.
    """
    title_lower = title.lower()

    # 1. Price threshold markets (worst category: 0.334 Brier)
    if _PRICE_THRESHOLD_RE.search(title):
        return "price_threshold"
    if _PRICE_ASSET_RE.search(title):
        return "price_asset"

    # 2. Obscure election/primary markets (0.226 Brier)
    if any(pat in title_lower for pat in _POLITICS_NOISE_PATTERNS):
        return "politics_noise"

    # 3. Coin-flip markets at midrange (model says 0.53 on everything)
    if 40 <= price_cents <= 60:
        if _IPO_PATTERN.search(title):
            return "coinflip_ipo"
        if any(pat in title_lower for pat in _COINFLIP_PATTERNS):
            return "coinflip_uncertain"

    return ""


def _is_blocked(ticker: str, category: str = "", title: str = "",
                price_cents: int = 50) -> bool:
    """Check if a market should be excluded from analysis.

    Three-layer filter:
      1. Ticker prefix blocklist (weather, intraday, entertainment)
      2. Category blocklist (sports, streaming, celebrities)
      3. Signal-quality gate (politics noise, price thresholds, coin-flips)
    """
    ticker_upper = ticker.upper()
    if any(ticker_upper.startswith(prefix) for prefix in _BLOCKED_TICKER_PREFIXES):
        return True
    if category and category.lower().strip() in _BLOCKED_CATEGORIES_API:
        return True
    title_lower = title.lower()
    if any(pat in title_lower for pat in _MICRO_TIMEFRAME_PATTERNS):
        return True

    # Signal-quality gate — block patterns with no LLM edge
    noise_reason = _is_noise_market(title, price_cents)
    if noise_reason:
        logger.debug(f"Signal filter: {noise_reason} — {title[:60]}")
        return True

    return False


def _is_sports(ticker: str, title: str) -> bool:
    combined = f"{ticker} {title}".lower()
    if any(tok in combined for tok in _SPORTS_TOKENS_SUBSTR):
        return True
    if _SPORTS_TOKENS_WORD_BOUNDARY.search(combined):
        return True
    return False


# ── Phase 1: Market Fetching ──────────────────────────────────────────────

def fetch_kalshi_markets(client, cfg: dict) -> list[dict]:
    """Fetch and pre-filter Kalshi markets.

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

    all_markets = []
    cursor = None
    fetch_start = time.time()
    max_fetch_seconds = cfg.get("max_fetch_seconds", 30)

    for page in range(max_pages):
        if time.time() - fetch_start > max_fetch_seconds:
            logger.info(f"Fetch: hit {max_fetch_seconds}s budget at page {page}")
            break

        try:
            # Construct API URL
            url = (
                "https://api.elections.kalshi.com/trade-api/v2/markets"
                "?limit=200&status=open&mve_filter=exclude"
            )
            if cursor:
                url += f"&cursor={cursor}"

            # Make API call
            resp = client.call_api("GET", url)
            data = json.loads(resp.read())

            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")

            if not cursor or not markets:
                break

            logger.info(f"Fetch: page {page}, got {len(markets)} markets (cursor: {cursor[:20] if cursor else 'none'})")

        except Exception as e:
            logger.error(f"Fetch error at page {page}: {e}")
            break

    logger.info(f"Fetch: {len(all_markets)} raw markets")

    # Pre-filter
    filtered = []
    stats = {"no_book": 0, "blocked": 0, "sports": 0, "volume": 0, "timeframe": 0}

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
            continue

        days_to_close = _calc_days_to_close(m)
        if days_to_close is None or days_to_close < min_days or days_to_close > max_days:
            stats["timeframe"] += 1
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
            "expiration_time": m.get("expiration_time", ""),
            "is_sports": is_sports,
        })

    logger.info(
        f"Fetch: {len(filtered)} passed filters (blocked={stats['blocked']}, "
        f"sports_tagged={stats['sports']}, volume={stats['volume']}, timeframe={stats['timeframe']})"
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


def _call_xpulse_estimate(market: dict) -> Optional[dict]:
    """Call Xpulse to get a second probability estimate via Claude CLI or Ollama.

    Primary: Claude Code CLI (`claude -p`) — routes through Max subscription.
    Fallback: Direct HTTP call to Ollama (localhost:11434).

    Args:
        market: Market dict with title, yes_price, etc.

    Returns:
        Dict with estimated_probability and confidence, or None if failed.
    """
    import subprocess as _sp

    title = market.get("title", "")
    price = market.get("yes_price", 50)
    days = market.get("days_to_close")

    xpulse_prompt = (
        f"You are a prediction market probability estimator focused on sentiment "
        f"and social signals. Given this market, estimate the true probability of YES.\n\n"
        f"MARKET: {title}\n"
        f"CURRENT PRICE: {price}¢\n"
        f"DAYS TO CLOSE: {days if days else 'unknown'}\n\n"
        f'Respond ONLY with JSON: {{"estimated_probability": <0.0-1.0>, '
        f'"confidence": <0.0-1.0>}}. No markdown, no explanation.'
    )

    # Try Claude CLI first (Max subscription — $0 cost)
    try:
        result = _sp.run(
            ["claude", "-p", xpulse_prompt, "--model", "haiku"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path.home()) if hasattr(Path, 'home') else "/tmp",
            start_new_session=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            import re as _re
            text = result.stdout.strip()
            text = _re.sub(r"```(?:json)?\s*", "", text)
            text = _re.sub(r"```\s*", "", text).strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                s, e = text.find("{"), text.rfind("}") + 1
                if s >= 0 and e > s:
                    parsed = json.loads(text[s:e])
                else:
                    parsed = None
            if parsed and "estimated_probability" in parsed:
                prob = max(0.01, min(0.99, float(parsed["estimated_probability"])))
                conf = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
                return {"estimated_probability": round(prob, 4), "confidence": round(conf, 4)}
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass
    except Exception as e:
        logger.debug(f"Xpulse CLI fallback: {e}")

    # Fallback: Ollama
    import urllib.request
    import urllib.error

    try:
        payload = json.dumps({
            "model": "qwen2.5:7b",
            "prompt": xpulse_prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 256},
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = data.get("response", "").strip()
        # Strip thinking blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Parse JSON
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(text[start:end])
            else:
                return None

        est_prob = float(result.get("estimated_probability", 0.5))
        confidence = float(result.get("confidence", 0.3))

        est_prob = max(0.01, min(0.99, est_prob))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "estimated_probability": round(est_prob, 4),
            "confidence": round(confidence, 4),
            "estimator": "xpulse",
        }

    except Exception as e:
        logger.debug(f"Xpulse estimation failed for '{market.get('title', '?')[:40]}': {e}")
        return None


def _compute_ensemble_estimate(
    kalshalyst_est: dict,
    xpulse_est: Optional[dict],
    market_price_cents: int,
    weights: dict,
) -> tuple[float, float]:
    """Combine estimates using ensemble weights.

    Args:
        kalshalyst_est: Kalshalyst estimate dict with estimated_probability, confidence
        xpulse_est: Xpulse estimate dict or None
        market_price_cents: Market price for weight
        weights: Dict with w_kalshalyst, w_xpulse, w_market

    Returns:
        Tuple of (ensemble_estimate, adjusted_confidence)
    """
    w_k = weights["w_kalshalyst"]
    w_x = weights["w_xpulse"]
    w_m = weights["w_market"]

    # Base probabilities
    k_prob = kalshalyst_est.get("estimated_probability", 0.5)
    x_prob = xpulse_est.get("estimated_probability", 0.5) if xpulse_est else 0.5
    m_prob = market_price_cents / 100.0

    # Weighted ensemble
    ensemble_prob = w_k * k_prob + w_x * x_prob + w_m * m_prob

    # Confidence: base on agreement between signals
    k_conf = kalshalyst_est.get("confidence", 0.3)
    x_conf = xpulse_est.get("confidence", 0.3) if xpulse_est else 0.3

    # Agreement bonus: if all 3 signals agree on side of 50%, boost confidence
    k_side = 1 if k_prob > 0.5 else -1 if k_prob < 0.5 else 0
    x_side = 1 if x_prob > 0.5 else -1 if x_prob < 0.5 else 0
    m_side = 1 if m_prob > 0.5 else -1 if m_prob < 0.5 else 0

    agreement_count = 0
    if k_side != 0:
        if x_side == k_side or x_side == 0:  # Xpulse agrees or neutral
            agreement_count += 1
        if m_side == k_side or m_side == 0:  # Market agrees or neutral
            agreement_count += 1

    # Confidence adjustment
    base_confidence = (k_conf + x_conf) / 2.0
    if agreement_count == 2:
        # All 3 signals agree on direction
        ensemble_confidence = base_confidence * 1.2  # Boost to 1.2x
    elif agreement_count == 1:
        # 2 of 3 agree on direction
        ensemble_confidence = base_confidence * 1.0
    else:
        # Signals disagree on direction
        ensemble_confidence = base_confidence * 0.7  # Reduce to 0.7x

    ensemble_confidence = max(0.0, min(1.0, ensemble_confidence))

    return ensemble_prob, ensemble_confidence


def calculate_edges(markets: list[dict], cfg: dict) -> list[dict]:
    """Phase 3+4: Claude estimation + edge calculation.

    If ensemble mode is enabled, combines Kalshalyst + Xpulse + market price
    using optimized weights. Falls back to Kalshalyst-only if ensemble fails.
    """
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

    # Load ensemble config
    ensemble_weights = _load_ensemble_weights(cfg)

    # If ensemble is enabled, augment estimates with Xpulse
    if ensemble_weights:
        logger.info("Ensemble mode ENABLED — augmenting Kalshalyst estimates with Xpulse")
        ensemble_results = []
        xpulse_count = 0
        xpulse_skipped = 0

        for r in results:
            market = {
                "title": r.get("title", ""),
                "yes_price": r.get("yes_price", 50),
                "days_to_close": r.get("days_to_close"),
            }

            # Try to get Xpulse estimate
            xpulse_est = _call_xpulse_estimate(market)

            if xpulse_est:
                xpulse_count += 1
                # Save original Kalshalyst estimate BEFORE overwriting
                original_kal_est = r.get("estimated_probability", 0.5)
                original_kal_conf = r.get("confidence", 0.3)

                # Combine estimates
                ensemble_prob, ensemble_conf = _compute_ensemble_estimate(
                    kalshalyst_est={
                        "estimated_probability": original_kal_est,
                        "confidence": original_kal_conf,
                    },
                    xpulse_est=xpulse_est,
                    market_price_cents=r.get("yes_price", 50),
                    weights=ensemble_weights,
                )

                # Log the ensemble computation
                logger.debug(
                    f"Ensemble for '{r.get('title', '?')[:40]}': "
                    f"Kalshalyst={original_kal_est:.3f}, "
                    f"Xpulse={xpulse_est.get('estimated_probability', 0.5):.3f}, "
                    f"Market={r.get('yes_price', 50)/100:.3f} → "
                    f"Ensemble={ensemble_prob:.3f} (conf={ensemble_conf:.3f})"
                )

                # Update result with ensemble estimate
                r["estimated_probability"] = round(ensemble_prob, 4)
                r["confidence"] = round(ensemble_conf, 4)
                r["estimator"] = "ensemble"
                r["ensemble_signals"] = {
                    "kalshalyst": original_kal_est,
                    "xpulse": xpulse_est.get("estimated_probability", 0.5),
                    "market_price": r.get("yes_price", 50) / 100.0,
                }

            else:
                xpulse_skipped += 1
                # Keep Kalshalyst estimate as-is
                logger.debug(
                    f"Xpulse failed for '{r.get('title', '?')[:40]}' — using Kalshalyst only"
                )
                r["estimator"] = "kalshalyst_only"

            ensemble_results.append(r)

        results = ensemble_results
        logger.info(f"Ensemble: {xpulse_count} Xpulse succeeded, {xpulse_skipped} skipped (fallback to Kalshalyst)")

    # Recalculate edges with updated estimates
    for r in results:
        market_implied = r.get("yes_price", 50) / 100.0
        est_prob = r.get("estimated_probability", 0.5)
        raw_edge_pct = abs(est_prob - market_implied) * 100
        spread_cost_pct = 0.0  # Limit orders

        direction = (
            "underpriced" if est_prob > market_implied
            else "overpriced" if est_prob < market_implied
            else "fair"
        )

        r["market_implied"] = round(market_implied, 4)
        r["direction"] = direction
        r["edge_pct"] = round(raw_edge_pct, 1)
        r["spread_cost_pct"] = round(spread_cost_pct, 1)
        r["effective_edge_pct"] = round(raw_edge_pct, 1)

    # No-confidence filter — when model returns ~0.50 it's saying "I don't know"
    # On 165-market eval: estimates in 0.48-0.55 range had 0.281 avg Brier (coin-flip)
    # vs 0.142 avg Brier for estimates outside that range. This is the single highest
    # impact filter: catches all noise the title-pattern filter misses.
    no_conf_lo = cfg.get("no_confidence_lo", 0.48)
    no_conf_hi = cfg.get("no_confidence_hi", 0.55)
    confident_results = []
    no_conf_count = 0
    for r in results:
        est = r.get("estimated_probability", 0.5)
        if no_conf_lo <= est <= no_conf_hi:
            no_conf_count += 1
            logger.debug(f"No-confidence skip: est={est:.2f} — {r.get('title', '?')[:50]}")
            continue
        confident_results.append(r)
    if no_conf_count:
        logger.info(f"Edge: {no_conf_count} markets skipped (no-confidence range {no_conf_lo}-{no_conf_hi})")

    # Filter by minimum edge
    min_edge = cfg.get("min_edge_pct", 3.0)
    edges = [r for r in confident_results if r.get("effective_edge_pct", 0) >= min_edge]

    edges.sort(key=lambda x: x.get("effective_edge_pct", 0), reverse=True)
    logger.info(f"Edge: {len(edges)} with >= {min_edge}% effective edge")

    return edges


def format_insight(edge: dict) -> dict:
    """Format edge result for output."""
    est = edge.get("estimated_probability", 0.5)
    mkt = edge.get("market_implied", 0.5)
    direction = edge.get("direction", "fair")

    result = {
        "ticker": edge.get("ticker", "?"),
        "title": edge.get("title", "?")[:60],
        "side": "YES" if direction == "underpriced" else "NO",
        "confidence": "high" if edge.get("confidence", 0) > 0.6 else "medium",
        "yes_bid": edge.get("yes_bid", 0),
        "yes_ask": edge.get("yes_ask", 0),
        "volume": edge.get("volume", 0),
        "open_interest": edge.get("open_interest", 0),
        "days_to_close": edge.get("days_to_close"),
        "market_prob": round(mkt, 4),
        "estimated_prob": round(est, 4),
        "edge_pct": edge.get("edge_pct", 0),
        "effective_edge_pct": edge.get("effective_edge_pct", 0),
        "direction": direction,
        "reasoning": edge.get("reasoning", ""),
        "estimator": edge.get("estimator", "unknown"),
    }

    # Include ensemble signal details if available
    if "ensemble_signals" in edge:
        result["ensemble_signals"] = edge["ensemble_signals"]

    # Include filter boost if applied
    if "filter_boost" in edge:
        result["filter_boost"] = edge["filter_boost"]

    return result


def run_kalshalyst(client, cfg: dict, dry_run: bool = False) -> bool:
    """Main Kalshalyst pipeline."""
    logger.info("=" * 60)
    logger.info("Kalshalyst starting (Claude contrarian estimation)...")
    logger.info("=" * 60)

    # Phase 1: Fetch
    markets = fetch_kalshi_markets(client, cfg)
    if not markets:
        logger.info("Kalshalyst: no markets passed filters")
        return False

    # Phase 3+4: Estimate + edge
    edges = calculate_edges(markets, cfg)

    # Phase 4.5: Eval-driven market filter (SKIP low-edge categories, BOOST high-edge)
    edges = _apply_market_filter(edges, cfg)

    # Phase 5: Cache + alert
    cache_payload = {
        "insights": [format_insight(e) for e in edges[:20]],
        "macro_count": len(edges),
        "total_scanned": len(markets),
        "scanner_version": "1.0.0",
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"Kalshalyst: {len(edges)} opportunities found")

    if dry_run:
        logger.info("[DRY RUN] Would write cache and send alerts")
        for e in edges[:3]:
            logger.info(f"  - {e.get('title', '?')[:40]} | {e.get('effective_edge_pct', 0):.1f}% edge")
        return True

    # Alert on high-edge opportunities
    alert_threshold = cfg.get("alert_edge_pct", 6.0)
    alert_candidates = [e for e in edges if e.get("effective_edge_pct", 0) >= alert_threshold]

    if alert_candidates:
        logger.info(f"Kalshalyst: {len(alert_candidates)} above alert threshold ({alert_threshold}%)")
        for i, e in enumerate(alert_candidates[:3], 1):
            side = "YES" if e.get("direction") == "underpriced" else "NO"
            logger.info(f"  {i}. {e.get('title', '?')[:45]}")
            logger.info(f"     {side} @ {e.get('market_implied', 0):.0%} | {e.get('effective_edge_pct', 0):.0f}% edge")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kalshalyst")
    parser.add_argument("--dry-run", action="store_true", help="Don't send alerts")
    parser.add_argument("--force", action="store_true", help="Force run (ignore interval)")

    args = parser.parse_args()

    # Initialize Kalshi client (you'll need to implement this with your config)
    # For now, this is a stub
    logger.error("Kalshi client not initialized — implement with your credentials")
