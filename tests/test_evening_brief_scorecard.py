"""Regression tests for the evening brief scorecard section."""

import sys
import types
from pathlib import Path
from unittest.mock import patch


BRIEF_PATH = Path(__file__).parent.parent / "market-morning-brief" / "scripts"
sys.path.insert(0, str(BRIEF_PATH))


def test_scorecard_section_handles_missing_ledger():
    from evening_brief import format_scorecard_section

    with patch.dict(sys.modules, {"trade_ledger": None}):
        result = format_scorecard_section({}, debug=False)

    assert "I don't know" in result


def test_scorecard_section_formats_monthly_metrics():
    from evening_brief import format_scorecard_section

    fake_scorecard = {
        "month": "2026-03",
        "wins": 3,
        "losses": 1,
        "total_pnl": 12.5,
        "best_trade": {"ticker": "BEST", "pnl": 8.0, "title": "Best trade title"},
        "worst_trade": {"ticker": "WORST", "pnl": -2.5, "title": "Worst trade title"},
        "edge_accuracy_pct": 75.0,
        "resolved_entries": 4,
        "confirmed_entries": 5,
    }

    fake_trade_ledger = types.SimpleNamespace(
        get_monthly_scorecard=lambda: fake_scorecard
    )

    with patch.dict(sys.modules, {"trade_ledger": fake_trade_ledger}):
        result = format_scorecard_section({}, debug=False)

    assert "3W / 1L" in result
    assert "$+12.50" in result
    assert "BEST" in result
    assert "WORST" in result
    assert "75.0%" in result
