"""CODEX: cache-contract tests for Market Morning Brief integration points."""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parent.parent
MORNING_BRIEF_PATH = ROOT / "market-morning-brief" / "scripts" / "morning_brief.py"


def load_morning_brief_module():
    """Import morning_brief.py from disk."""
    spec = importlib.util.spec_from_file_location("codex_morning_brief", MORNING_BRIEF_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, payload):
    """Persist a JSON payload for a cache-contract test."""
    path.write_text(json.dumps(payload))


def test_check_cache_age_supports_iso_cached_at(tmp_path):
    """CODEX: cache freshness should work with ISO timestamps."""
    module = load_morning_brief_module()
    cache_file = tmp_path / "kalshalyst_cache.json"
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    write_json(cache_file, {"cached_at": fresh_ts})

    freshness, age_seconds = module.check_cache_age(cache_file, 3600)

    assert freshness == "fresh"
    assert 0 <= age_seconds < 3600


def test_check_cache_age_supports_unix_timestamp(tmp_path):
    """CODEX: cache freshness should also work with legacy unix timestamps."""
    module = load_morning_brief_module()
    cache_file = tmp_path / "arbiter_cache.json"
    fresh_ts = datetime.now(timezone.utc).timestamp() - 120
    write_json(cache_file, {"timestamp": fresh_ts})

    freshness, age_seconds = module.check_cache_age(cache_file, 3600)

    assert freshness == "fresh"
    assert 0 <= age_seconds < 3600


def test_format_kalshalyst_section_uses_yes_for_bullish_edge(tmp_path):
    """CODEX: a higher estimate than market price should render as a YES opportunity."""
    module = load_morning_brief_module()
    cache_file = tmp_path / "kalshalyst_cache.json"
    write_json(
        cache_file,
        {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "insights": [
                {
                    "ticker": "FED-RATE-MAY",
                    "market_prob": 0.42,
                    "estimated_prob": 0.61,
                    "edge_pct": 19,
                    "confidence": 0.74,
                }
            ],
        },
    )

    rendered = module.format_kalshalyst_section(cache_file, {})

    assert "YES @" in rendered
    assert "NO @" not in rendered


def test_format_arbiter_section_supports_normalized_schema(tmp_path):
    """CODEX: Morning Brief should accept the current arbiter cache schema."""
    module = load_morning_brief_module()
    cache_file = tmp_path / "arbiter_cache.json"
    write_json(
        cache_file,
        {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "divergences": [
                {
                    "ticker": "INFL-2026",
                    "kalshi_price": 0.44,
                    "polymarket_price": 0.51,
                    "spread_cents": 7,
                }
            ],
        },
    )

    rendered = module.format_arbiter_section(cache_file, {})

    assert "Kalshi 44% ↔ PM 51%" in rendered
    assert "(7¢ spread)" in rendered


def test_format_arbiter_section_supports_legacy_schema(tmp_path):
    """CODEX: Morning Brief should stay compatible with older arbiter cache payloads."""
    module = load_morning_brief_module()
    cache_file = tmp_path / "arbiter_cache_legacy.json"
    write_json(
        cache_file,
        {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "matches": [
                {
                    "kalshi_title": "Jobs Report",
                    "kalshi_price": 46,
                    "pm_price": 52,
                    "delta": 6,
                }
            ],
        },
    )

    rendered = module.format_arbiter_section(cache_file, {})

    assert "Kalshi 46% ↔ PM 52%" in rendered
    assert "(6¢ spread)" in rendered


def test_load_config_defaults_point_to_runtime_cache_locations():
    """CODEX: default config should match the runtime cache files emitted by the skills."""
    module = load_morning_brief_module()

    config = module.load_config()

    assert config["cache_paths"]["kalshalyst"].endswith(".openclaw/state/kalshalyst_cache.json")
    assert config["cache_paths"]["arbiter"].endswith(".openclaw/state/arbiter_cache.json")
    assert config["cache_paths"]["xpulse"].endswith(".openclaw/state/x_signal_cache.json")
