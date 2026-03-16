"""Test trade ledger — append-only local record of all executions.

Validates:
  - Trades are recorded and retrievable
  - Positions can be closed with P&L
  - Open positions aggregate correctly
  - Ledger survives corrupt/missing file
  - Dry runs don't appear in open positions
"""

import pytest
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add kalshalyst scripts to path
KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))


@pytest.fixture(autouse=True)
def temp_ledger(tmp_path):
    """Redirect ledger to temp file for each test."""
    ledger_path = tmp_path / "trade_ledger.json"
    with patch("trade_ledger.LEDGER_PATH", ledger_path):
        yield ledger_path


class TestRecordTrade:
    """Recording trades to the ledger."""

    def test_record_creates_entry(self):
        from trade_ledger import record_trade, get_ledger

        record_trade(
            ticker="KXSHUTDOWN-43D", side="yes", contracts=50,
            price_cents=58, cost_usd=29.00, title="Shutdown 43 days"
        )

        ledger = get_ledger()
        assert len(ledger) == 1
        assert ledger[0]["ticker"] == "KXSHUTDOWN-43D"
        assert ledger[0]["side"] == "yes"
        assert ledger[0]["contracts"] == 50
        assert ledger[0]["status"] == "open"

    def test_multiple_trades_append(self):
        from trade_ledger import record_trade, get_ledger

        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        record_trade(ticker="T2", side="no", contracts=20, price_cents=30, cost_usd=6.00)
        record_trade(ticker="T3", side="yes", contracts=5, price_cents=80, cost_usd=4.00)

        ledger = get_ledger()
        assert len(ledger) == 3
        assert [e["ticker"] for e in ledger] == ["T1", "T2", "T3"]

    def test_dry_run_recorded_with_flag(self):
        from trade_ledger import record_trade, get_ledger

        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50,
                      cost_usd=5.00, dry_run=True)

        ledger = get_ledger()
        assert len(ledger) == 1
        assert ledger[0]["dry_run"] is True


class TestOpenPositions:
    """Getting currently open positions."""

    def test_open_positions_returns_open_only(self):
        from trade_ledger import record_trade, close_position, get_open_positions

        record_trade(ticker="OPEN1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        record_trade(ticker="CLOSED1", side="no", contracts=20, price_cents=30, cost_usd=6.00)
        close_position("CLOSED1", reason="resolved", pnl=4.00)

        positions = get_open_positions()
        assert "OPEN1" in positions
        assert "CLOSED1" not in positions

    def test_dry_runs_excluded_from_open(self):
        from trade_ledger import record_trade, get_open_positions

        record_trade(ticker="DRY1", side="yes", contracts=10, price_cents=50,
                      cost_usd=5.00, dry_run=True)
        record_trade(ticker="REAL1", side="yes", contracts=10, price_cents=50,
                      cost_usd=5.00, dry_run=False)

        positions = get_open_positions()
        assert "DRY1" not in positions
        assert "REAL1" in positions

    def test_same_ticker_sums_contracts(self):
        from trade_ledger import record_trade, get_open_positions

        record_trade(ticker="SAME", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        record_trade(ticker="SAME", side="yes", contracts=15, price_cents=55, cost_usd=8.25)

        positions = get_open_positions()
        assert positions["SAME"]["contracts"] == 25
        assert positions["SAME"]["cost_usd"] == 13.25

    def test_empty_ledger_returns_empty(self):
        from trade_ledger import get_open_positions
        assert get_open_positions() == {}


class TestClosePosition:
    """Closing positions in the ledger."""

    def test_close_marks_status(self):
        from trade_ledger import record_trade, close_position, get_ledger

        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        close_position("T1", reason="resolved", pnl=3.00)

        ledger = get_ledger()
        assert ledger[0]["status"] == "closed"
        assert ledger[0]["close_reason"] == "resolved"
        assert ledger[0]["pnl"] == 3.00

    def test_close_nonexistent_returns_false(self):
        from trade_ledger import close_position
        assert close_position("NONEXISTENT") is False

    def test_close_most_recent_open(self):
        """If same ticker opened twice, close the newest one."""
        from trade_ledger import record_trade, close_position, get_ledger

        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        record_trade(ticker="T1", side="yes", contracts=20, price_cents=55, cost_usd=11.00)
        close_position("T1", reason="sold", pnl=2.00)

        ledger = get_ledger()
        # First entry still open, second closed
        assert ledger[0]["status"] == "open"
        assert ledger[1]["status"] == "closed"


class TestSummary:
    """Ledger summary statistics."""

    def test_summary_counts(self):
        from trade_ledger import record_trade, close_position, get_summary

        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        record_trade(ticker="T2", side="no", contracts=20, price_cents=30, cost_usd=6.00)
        record_trade(ticker="T3", side="yes", contracts=5, price_cents=80, cost_usd=4.00, dry_run=True)
        close_position("T2", reason="resolved", pnl=4.00)

        summary = get_summary()
        assert summary["total_trades"] == 2  # excludes dry run
        assert summary["open_positions"] == 1
        assert summary["closed_positions"] == 1
        assert summary["total_deployed_usd"] == 5.00  # only open
        assert summary["total_realized_pnl"] == 4.00


class TestResilience:
    """Ledger handles corrupt and missing files."""

    def test_missing_file_returns_empty(self, tmp_path):
        from trade_ledger import get_open_positions
        # Ledger file doesn't exist yet — should return empty, not crash
        assert get_open_positions() == {}

    def test_corrupt_file_returns_empty(self, tmp_path):
        from trade_ledger import get_ledger, LEDGER_PATH

        # Write garbage to the ledger file
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "w") as f:
            f.write("NOT VALID JSON {{{")

        ledger = get_ledger()
        assert ledger == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
