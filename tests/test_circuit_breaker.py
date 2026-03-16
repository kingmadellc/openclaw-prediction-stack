"""Test circuit breaker — detect and flag contradictory API responses.

Validates:
  - Trips when API returns 0 positions but ledger shows open positions
  - Trips when position count drops massively
  - Does NOT trip on normal portfolio changes
  - Recovers when API returns consistent data
  - Returns last known state when tripped

These tests would have caught March 13's "no positions" false reports.
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch

KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))


@pytest.fixture(autouse=True)
def temp_state(tmp_path):
    """Redirect all state files to temp dir for each test."""
    snapshot_path = tmp_path / "portfolio_snapshot.json"
    breaker_path = tmp_path / "circuit_breaker.json"
    ledger_path = tmp_path / "trade_ledger.json"

    with patch("circuit_breaker.SNAPSHOT_PATH", snapshot_path), \
         patch("circuit_breaker.BREAKER_STATE_PATH", breaker_path), \
         patch("trade_ledger.LEDGER_PATH", ledger_path):
        yield tmp_path


class TestTripsOnEmptyResponse:
    """THE critical test: API returns empty when positions exist."""

    def test_trips_when_api_empty_but_ledger_has_positions(self):
        """This is the exact March 13 bug."""
        from trade_ledger import record_trade
        from circuit_breaker import check_portfolio, _write_snapshot

        # Set up: we had 5 positions last check
        _write_snapshot(
            positions={"T1": {}, "T2": {}, "T3": {}, "T4": {}, "T5": {}},
            balance=47.75,
            position_count=5,
        )

        # Ledger also knows about some positions
        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)
        record_trade(ticker="T2", side="no", contracts=20, price_cents=30, cost_usd=6.00)

        # API returns empty (the bug)
        state = check_portfolio(
            api_positions={},
            api_balance=47.75,
            api_position_count=0,
        )

        assert state.is_tripped is True, "Circuit breaker should have tripped"
        assert "0 positions" in state.trip_reason
        assert state.confidence == "stale"

    def test_does_not_trip_on_genuinely_empty_portfolio(self):
        """First-ever check with no snapshot and no ledger entries."""
        from circuit_breaker import check_portfolio

        state = check_portfolio(
            api_positions={},
            api_balance=100.00,
            api_position_count=0,
        )

        assert state.is_tripped is False

    def test_does_not_trip_when_snapshot_also_empty(self):
        """If last snapshot was also empty, API returning empty is fine."""
        from circuit_breaker import check_portfolio, _write_snapshot

        _write_snapshot(positions={}, balance=100.00, position_count=0)

        state = check_portfolio(
            api_positions={},
            api_balance=100.00,
            api_position_count=0,
        )

        assert state.is_tripped is False


class TestTripsOnMassivePositionDrop:
    """Trips when positions vanish without explanation."""

    def test_trips_when_many_positions_vanish(self):
        from circuit_breaker import check_portfolio, _write_snapshot

        # Had 8 positions last check
        _write_snapshot(
            positions={f"T{i}": {} for i in range(8)},
            balance=50.00,
            position_count=8,
        )

        # Now API says only 2
        state = check_portfolio(
            api_positions={"T0": {}, "T1": {}},
            api_balance=50.00,
            api_position_count=2,
        )

        assert state.is_tripped is True
        assert "vanished" in state.trip_reason

    def test_does_not_trip_on_small_position_change(self):
        """Closing 1-2 positions is normal."""
        from circuit_breaker import check_portfolio, _write_snapshot

        _write_snapshot(
            positions={"T1": {}, "T2": {}, "T3": {}},
            balance=50.00,
            position_count=3,
        )

        # Closed one position — normal
        state = check_portfolio(
            api_positions={"T1": {}, "T2": {}},
            api_balance=60.00,
            api_position_count=2,
        )

        assert state.is_tripped is False


class TestRecovery:
    """Circuit breaker recovers when API returns consistent data."""

    def test_recovers_after_consistent_data(self):
        from trade_ledger import record_trade
        from circuit_breaker import check_portfolio, _write_snapshot, is_tripped

        # First: trip it
        _write_snapshot(
            positions={"T1": {}},
            balance=50.00,
            position_count=1,
        )
        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)

        state1 = check_portfolio(api_positions={}, api_balance=50.00, api_position_count=0)
        assert state1.is_tripped is True
        assert is_tripped() is True

        # Now API returns good data (position resolved, ledger cleared)
        from trade_ledger import close_position
        close_position("T1", reason="resolved")

        state2 = check_portfolio(
            api_positions={},
            api_balance=55.00,
            api_position_count=0,
        )
        assert state2.is_tripped is False
        assert is_tripped() is False


class TestLastKnownState:
    """When tripped, last known good state is available."""

    def test_last_known_positions_populated(self):
        from trade_ledger import record_trade
        from circuit_breaker import check_portfolio, _write_snapshot

        old_positions = {"T1": {"side": "yes"}, "T2": {"side": "no"}}
        _write_snapshot(positions=old_positions, balance=75.00, position_count=2)
        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)

        state = check_portfolio(api_positions={}, api_balance=75.00, api_position_count=0)

        assert state.is_tripped is True
        assert state.last_known_positions == old_positions
        assert state.last_known_balance == 75.00


class TestStatus:
    """Diagnostic status reporting."""

    def test_status_after_trip(self):
        from trade_ledger import record_trade
        from circuit_breaker import check_portfolio, _write_snapshot, get_status

        _write_snapshot(positions={"T1": {}}, balance=50.00, position_count=1)
        record_trade(ticker="T1", side="yes", contracts=10, price_cents=50, cost_usd=5.00)

        check_portfolio(api_positions={}, api_balance=50.00, api_position_count=0)

        status = get_status()
        assert status["tripped"] is True
        assert status["trip_count"] >= 1
        assert status["ledger_open_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
