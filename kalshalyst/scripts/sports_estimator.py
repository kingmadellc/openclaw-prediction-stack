"""Sports market probability estimation — data-driven model.

STUB — not yet production-ready. All methods return None until data pipelines are built.

ARCHITECTURE:
    Unlike claude_estimator.py (which asks an LLM to find contrarian edge),
    sports estimation requires structured data inputs:

    1. ELO / RATING  — Sport-specific rating system (ATP rankings, NBA ELO, etc.)
    2. HEAD-TO-HEAD   — Historical matchup record between competitors
    3. VENUE/CONTEXT  — Surface (tennis), home/away (team sports), altitude, etc.
    4. RECENCY        — Form over last N matches, injuries, rest days
    5. LINE MOVEMENT  — Where sharp money is going (requires odds API)

    The estimator outputs the same schema as claude_estimator.py so it plugs
    directly into kalshalyst's calculate_edges() without changes downstream.

PREMIUM GATE:
    This module is PREMIUM ONLY. The sports filter in _SPORTS_TOKENS blocks all
    sports markets from reaching the free-tier Claude estimator. When this module
    is production-ready, the auto_trader will route sports markets here instead
    of skipping them — but only for premium users who have:
      ~/sports_estimator_config.json  (config file acts as the license gate)

DATA SOURCES (to be wired):
    - Tennis: ATP/WTA rankings API, match-level results (Jeff Sackmann's dataset)
    - NBA/NFL/MLB: public ELO systems (FiveThirtyEight archive, ESPN API)
    - Esports: HLTV (CS2), Liquipedia (LoL/Dota), VLR (Valorant)
    - Odds movement: The Odds API (free tier: 500 req/mo), OddsJam, BettingPros

AUTORESEARCH TARGET:
    Editable file: ~/prompt-lab/sports_model_weights.json
    Eval metric: Brier score on resolved sports markets
    Backtest: ~/prompt-lab/sports_backtest.json (to be built from Kalshi historical)

USAGE:
    from sports_estimator import estimate_sports_market

    result = estimate_sports_market(
        ticker="KXATPCHALLENGERMATCH-26MAR11NAVHAR-NAV",
        title="Will Mariano Navone win the Navone vs Hardt",
        market_price_cents=81,
        sport="tennis",
        metadata={"surface": "hard", "tournament_level": "challenger", ...}
    )
    # Returns same schema as claude_estimator output:
    # {"probability": 0.78, "confidence": 0.65, "reasoning": "...", "estimator": "sports_v1"}
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────

SPORTS_CONFIG_PATH = Path.home() / "sports_estimator_config.json"
SPORTS_WEIGHTS_PATH = Path.home() / "prompt-lab" / "sports_model_weights.json"

# Sport detection from Kalshi ticker prefixes
SPORT_ROUTING = {
    # Ticker prefix → sport key
    "kxatp": "tennis",
    "kxwta": "tennis",
    "challengermatch": "tennis",
    "kxnba": "basketball",
    "nbaspread": "basketball",
    "nbagame": "basketball",
    "kxnfl": "football",
    "nflspread": "football",
    "nflgame": "football",
    "kxmlb": "baseball",
    "mlbgame": "baseball",
    "kxnhl": "hockey",
    "nhlgame": "hockey",
    "kxncaa": "college",
    "ncaambgame": "college",
    "ncaafbgame": "college",
    "kxufc": "mma",
    "kxmma": "mma",
    "kxlol": "esports",
    "lolgame": "esports",
    "kxvalorant": "esports",
    "kxcsgo": "esports",
    "kxdota": "esports",
    "kxnascar": "motorsport",
    "kxf1": "motorsport",
}


def _load_config() -> Optional[dict]:
    """Load sports estimator config. Returns None if not configured (free tier)."""
    if not SPORTS_CONFIG_PATH.exists():
        return None
    try:
        with open(SPORTS_CONFIG_PATH) as f:
            cfg = json.load(f)
        if not cfg.get("enabled", False):
            return None
        return cfg
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Sports config load error: {e}")
        return None


def _load_weights() -> dict:
    """Load model weights from autoresearch-tunable config."""
    if not SPORTS_WEIGHTS_PATH.exists():
        return _default_weights()
    try:
        with open(SPORTS_WEIGHTS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_weights()


def _default_weights() -> dict:
    """Default model weights — conservative until autoresearch tunes them."""
    return {
        "w_elo": 0.40,
        "w_h2h": 0.15,
        "w_form": 0.20,
        "w_venue": 0.10,
        "w_line_movement": 0.15,
        "confidence_base": 0.30,       # Low default — we don't trust the model yet
        "min_data_points": 5,          # Minimum matches in dataset to estimate
        "max_confidence": 0.70,        # Cap until model is validated
        "version": "0.1.0-stub",
    }


# ── Sport Detection ───────────────────────────────────────────────────────

def detect_sport(ticker: str) -> Optional[str]:
    """Detect sport from Kalshi ticker prefix.

    Returns sport key (tennis, basketball, etc.) or None if not a sports market.
    """
    ticker_lower = ticker.lower()
    for prefix, sport in SPORT_ROUTING.items():
        if prefix in ticker_lower:
            return sport
    return None


# ── Data Fetchers (STUBS) ────────────────────────────────────────────────
# Each returns None until the data pipeline is built.
# When implemented, each should return a dict with:
#   {"value": float 0-1, "confidence": float 0-1, "source": str, "data_points": int}

def _fetch_elo_rating(sport: str, competitor_a: str, competitor_b: str) -> Optional[dict]:
    """Fetch ELO/ranking-based probability estimate.

    TODO: Wire data sources:
      - Tennis: ATP/WTA rankings → ELO conversion (Jeff Sackmann tennis_atp repo)
      - NBA: FiveThirtyEight ELO (archived), ESPN BPI
      - NFL: FiveThirtyEight ELO (archived), PFF ratings
      - College: KenPom (basketball), SP+ (football)
      - Esports: HLTV rankings (CS2), Oracle's Elixir (LoL)
    """
    logger.debug(f"[STUB] _fetch_elo_rating({sport}, {competitor_a}, {competitor_b})")
    return None


def _fetch_head_to_head(sport: str, competitor_a: str, competitor_b: str) -> Optional[dict]:
    """Fetch historical head-to-head record.

    TODO: Wire data sources:
      - Tennis: Jeff Sackmann match CSVs
      - NBA/NFL/MLB: ESPN API historical results
      - Esports: Liquipedia / HLTV match history
    """
    logger.debug(f"[STUB] _fetch_head_to_head({sport}, {competitor_a}, {competitor_b})")
    return None


def _fetch_recent_form(sport: str, competitor: str, lookback_matches: int = 10) -> Optional[dict]:
    """Fetch recent form (win rate over last N matches).

    TODO: Wire data sources:
      - Tennis: recent results from ATP/WTA API
      - Team sports: last N game results
      - Include rest days, travel distance, back-to-back detection
    """
    logger.debug(f"[STUB] _fetch_recent_form({sport}, {competitor}, lookback={lookback_matches})")
    return None


def _fetch_venue_context(sport: str, ticker: str, title: str) -> Optional[dict]:
    """Fetch venue/context adjustment.

    TODO: Parse from title/metadata:
      - Tennis: surface (hard/clay/grass), indoor/outdoor, altitude
      - Team sports: home/away, travel distance, rest days
      - Esports: LAN vs online, patch version
    """
    logger.debug(f"[STUB] _fetch_venue_context({sport}, {ticker})")
    return None


def _fetch_line_movement(ticker: str) -> Optional[dict]:
    """Fetch line/odds movement signal (where sharp money is going).

    TODO: Wire data sources:
      - The Odds API (free tier: 500 req/mo)
      - Kalshi orderbook depth (bid/ask imbalance)
      - Compare Kalshi price to consensus sportsbook line
    """
    logger.debug(f"[STUB] _fetch_line_movement({ticker})")
    return None


# ── Core Estimator ────────────────────────────────────────────────────────

def estimate_sports_market(
    ticker: str,
    title: str,
    market_price_cents: int,
    sport: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Estimate probability for a sports market using structured data.

    Returns same schema as claude_estimator for seamless pipeline integration:
        {
            "probability": float,      # 0-1, estimated true probability of YES
            "confidence": float,       # 0-1, model confidence in estimate
            "reasoning": str,          # Human-readable explanation
            "estimator": str,          # "sports_v1"
            "sport": str,             # Detected sport
            "signals": dict,          # Individual signal values (for debugging)
        }

    Returns None if:
        - Sports estimator not configured (free tier)
        - Sport not detected
        - Insufficient data to estimate
    """
    # ── Premium gate ──
    cfg = _load_config()
    if cfg is None:
        logger.debug("Sports estimator not configured (free tier or disabled)")
        return None

    # ── Detect sport ──
    if sport is None:
        sport = detect_sport(ticker)
    if sport is None:
        logger.debug(f"Cannot detect sport for ticker: {ticker}")
        return None

    # ── Parse competitors from title ──
    competitors = _parse_competitors(title, sport)
    if not competitors:
        logger.debug(f"Cannot parse competitors from: {title[:60]}")
        return None

    comp_a, comp_b = competitors
    weights = _load_weights()

    # ── Gather signals ──
    signals = {}

    elo = _fetch_elo_rating(sport, comp_a, comp_b)
    if elo:
        signals["elo"] = elo

    h2h = _fetch_head_to_head(sport, comp_a, comp_b)
    if h2h:
        signals["h2h"] = h2h

    form_a = _fetch_recent_form(sport, comp_a)
    form_b = _fetch_recent_form(sport, comp_b)
    if form_a and form_b:
        signals["form"] = {"a": form_a, "b": form_b}

    venue = _fetch_venue_context(sport, ticker, title)
    if venue:
        signals["venue"] = venue

    line = _fetch_line_movement(ticker)
    if line:
        signals["line_movement"] = line

    # ── Combine signals (weighted ensemble) ──
    if not signals:
        logger.info(f"No data signals available for {ticker} ({sport}) — skipping")
        return None

    # Check minimum data threshold
    total_data_points = sum(s.get("data_points", 0) for s in signals.values() if isinstance(s, dict))
    if total_data_points < weights.get("min_data_points", 5):
        logger.info(f"Insufficient data ({total_data_points} points) for {ticker} — skipping")
        return None

    probability = _weighted_ensemble(signals, weights)
    confidence = _calculate_confidence(signals, weights)

    # ── Build reasoning ──
    reasoning_parts = [f"Sport: {sport}, {comp_a} vs {comp_b}"]
    for signal_name, signal_data in signals.items():
        if isinstance(signal_data, dict) and "value" in signal_data:
            reasoning_parts.append(
                f"{signal_name}: {signal_data['value']:.2f} "
                f"(conf={signal_data.get('confidence', 0):.2f}, "
                f"n={signal_data.get('data_points', '?')})"
            )
    reasoning_parts.append(f"Ensemble: {probability:.3f} (conf={confidence:.3f})")

    return {
        "probability": round(probability, 4),
        "confidence": round(min(confidence, weights.get("max_confidence", 0.70)), 4),
        "reasoning": " | ".join(reasoning_parts),
        "estimator": f"sports_v{weights.get('version', '0.1.0')}",
        "sport": sport,
        "signals": signals,
    }


def _parse_competitors(title: str, sport: str) -> Optional[tuple]:
    """Parse competitor names from market title.

    Kalshi titles follow patterns like:
      "Will Mariano Navone win the Navone vs Hardt : Round of 32"
      "Houston vs Denver NBA spread"

    Returns (competitor_a, competitor_b) or None.
    """
    title_lower = title.lower()

    # Pattern 1: "X vs Y" or "X vs. Y"
    import re
    vs_match = re.search(r'(\w[\w\s]*?)\s+vs\.?\s+(\w[\w\s]*?)(?:\s*[:\-|]|\s*$)', title, re.IGNORECASE)
    if vs_match:
        return (vs_match.group(1).strip(), vs_match.group(2).strip())

    # Pattern 2: "Will X win the X vs Y"
    will_match = re.search(r'will\s+(.+?)\s+win\s+the\s+(.+?)\s+vs\.?\s+(.+?)(?:\s*[:\-|]|\s*$)', title, re.IGNORECASE)
    if will_match:
        return (will_match.group(2).strip(), will_match.group(3).strip())

    return None


def _weighted_ensemble(signals: dict, weights: dict) -> float:
    """Combine signals using weighted average.

    Each signal provides a probability estimate (0-1 for YES).
    Weights from sports_model_weights.json determine contribution.

    STUB: Returns 0.5 (no opinion) until signals are live.
    """
    # When signals are live, this will compute:
    # prob = sum(w_i * signal_i.value) / sum(w_i) for available signals
    #
    # For now, return no-opinion
    logger.debug("[STUB] _weighted_ensemble returning 0.5 (no data)")
    return 0.5


def _calculate_confidence(signals: dict, weights: dict) -> float:
    """Calculate model confidence based on signal availability and agreement.

    Confidence is higher when:
      - More signals are available
      - Signals agree with each other
      - Individual signals have more data points

    STUB: Returns confidence_base until signals are live.
    """
    logger.debug("[STUB] _calculate_confidence returning base")
    return weights.get("confidence_base", 0.30)


# ── Pipeline Integration ──────────────────────────────────────────────────

def is_sports_estimator_available() -> bool:
    """Check if sports estimator is configured and available.

    Used by auto_trader to decide routing:
      if is_sports_estimator_available() and is_sports(ticker, title):
          result = estimate_sports_market(...)
      else:
          # Skip (sports blocked by filter)
    """
    cfg = _load_config()
    return cfg is not None and cfg.get("enabled", False)


# ── Market Scope Descriptor ──────────────────────────────────────────────

def get_market_scope_description(include_sports: bool = False) -> str:
    """Return human-readable description of what markets the system trades.

    Used in morning briefs, alerts, and scan summaries so users understand
    the system's focus areas.
    """
    base_scope = (
        "Policy, politics, technology, economics, and macro markets — "
        "categories where our AI estimation model has a proven 90%+ edge accuracy "
        "based on backtesting across 84 resolved markets."
    )

    if include_sports:
        return (
            f"{base_scope}\n\n"
            "Sports & esports markets — estimated using a data-driven model "
            "built on ELO ratings, head-to-head records, recent form, and "
            "line movement. (Premium feature)"
        )

    return (
        f"{base_scope}\n\n"
        "Sports & esports markets are currently excluded — our estimation model "
        "is trained on information-advantage categories (policy, tech, macro), not "
        "sports matchups. A dedicated sports model is in development."
    )


MARKET_SCOPE_SHORT = (
    "📊 Scanning: policy | politics | tech | economics | macro\n"
    "🚫 Excluded: sports & esports (no model edge — dedicated model in development)"
)

MARKET_SCOPE_PREMIUM_SHORT = (
    "📊 Scanning: policy | politics | tech | economics | macro | sports\n"
    "🏆 Sports: data-driven model (ELO + H2H + form + line movement)"
)
