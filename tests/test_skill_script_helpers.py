"""Integration tests for skill script helpers (Slack, exit rules, normalization, sports filter).

These tests import real skill scripts that depend on kalshi_python_sync, pyyaml,
and other packages not available in CI.  The entire module is skipped when the
local skill tree at ~/skills/ is not present.
"""
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path.home()
_LOCAL_SKILLS = ROOT / "skills" / "kalshalyst"

if not _LOCAL_SKILLS.exists():
    pytest.skip(
        "requires local skill scripts at ~/skills/",
        allow_module_level=True,
    )


def _load_module(module_path: Path, extra_sys_paths=()):
    inserted = []
    for extra_path in extra_sys_paths:
        extra_str = str(extra_path)
        if extra_str not in sys.path:
            sys.path.insert(0, extra_str)
            inserted.append(extra_str)

    try:
        spec = importlib.util.spec_from_file_location(
            f"test_module_{module_path.stem}_{uuid.uuid4().hex}",
            module_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for extra_str in reversed(inserted):
            sys.path.remove(extra_str)


AUTO_TRADER_PATH = ROOT / "skills" / "kalshalyst" / "scripts" / "auto_trader.py"
AUTO_TRADER = _load_module(
    AUTO_TRADER_PATH,
    extra_sys_paths=(AUTO_TRADER_PATH.parent,),
)
PORTFOLIO_DRIFT_PATH = ROOT / "skills" / "portfolio-drift-monitor" / "scripts" / "portfolio_drift.py"
PORTFOLIO_DRIFT = _load_module(PORTFOLIO_DRIFT_PATH)
XPULSE_PATH = ROOT / "skills" / "xpulse" / "scripts" / "xpulse.py"
XPULSE = _load_module(XPULSE_PATH)
MORNING_BRIEF_PATH = ROOT / "skills" / "market-morning-brief" / "scripts" / "morning_brief.py"
MORNING_BRIEF = _load_module(MORNING_BRIEF_PATH)
KALSHALYST_PATH = ROOT / "skills" / "kalshalyst" / "scripts" / "kalshalyst.py"
KALSHALYST = _load_module(KALSHALYST_PATH, extra_sys_paths=(KALSHALYST_PATH.parent,))


def _assert_slack_payload(monkeypatch, module, message):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return object()

    monkeypatch.setenv("OPENCLAW_SLACK_WEBHOOK", "https://hooks.slack.test/services/T000/B000/XXX")
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    module._notify_slack(message)

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "https://hooks.slack.test/services/T000/B000/XXX"
    assert timeout in (5, 10)
    assert json.loads(request.data.decode("utf-8")) == {"text": message}
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["content-type"] == "application/json"


def test_auto_trader_notify_slack_formats_payload(monkeypatch):
    _assert_slack_payload(monkeypatch, AUTO_TRADER, "auto-trader test")


def test_portfolio_drift_notify_slack_formats_payload(monkeypatch):
    _assert_slack_payload(monkeypatch, PORTFOLIO_DRIFT, "portfolio drift test")


def test_xpulse_notify_slack_formats_payload(monkeypatch):
    _assert_slack_payload(monkeypatch, XPULSE, "xpulse test")


def test_morning_brief_notify_slack_formats_payload(monkeypatch):
    _assert_slack_payload(monkeypatch, MORNING_BRIEF, "morning brief test")


def test_load_exit_rules_parses_temp_markdown(monkeypatch, tmp_path):
    prompt_lab_dir = tmp_path / "prompt-lab"
    prompt_lab_dir.mkdir()
    (prompt_lab_dir / "exit_rules.md").write_text(
        "\n".join(
            [
                "# Exit Rules",
                "Min edge: 7.5",
                "Max hold hours: 48",
                "- ignored bullet: no",
                "strategy mode: trailing",
            ]
        )
    )

    monkeypatch.setattr(AUTO_TRADER.Path, "home", classmethod(lambda cls: tmp_path))

    rules = AUTO_TRADER._load_exit_rules()

    assert rules == {
        "min_edge": 7.5,
        "max_hold_hours": 48.0,
        "strategy_mode": "trailing",
    }


def test_normalize_position_maps_market_exposure_dollars():
    normalized = PORTFOLIO_DRIFT._normalize_position(
        {
            "event_ticker": "FEDCUTS-2026-Q3",
            "market_exposure_dollars": "42.50",
            "total_cost_dollars": "18.25",
        }
    )

    assert normalized["ticker"] == "FEDCUTS-2026-Q3"
    assert normalized["exposure"] == "42.50"
    assert normalized["total_cost"] == "18.25"


def test_is_sports_blocks_wta_ticker_patterns():
    assert KALSHALYST._is_sports("KXWTAMATCH-26MAR12PEGRYB", "Will Pegula win?") is True
    assert KALSHALYST._is_sports("KXWTACHALLENGERMATCH-26MAR12ANDJON", "Random title") is True
