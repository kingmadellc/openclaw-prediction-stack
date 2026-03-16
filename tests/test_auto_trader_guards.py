"""Test that auto_trader refuses to execute sports markets.

Defense-in-depth: even if kalshalyst's filter fails, auto_trader must
independently block any edge with is_sports=True from execution.

This test would have caught the $62.56 loss on March 13, 2026.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add kalshalyst scripts to path
KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))


def _make_mock_edge(ticker: str, title: str, is_sports: bool = False,
                    effective_edge: float = 8.0, confidence: float = 0.7,
                    direction: str = "underpriced") -> dict:
    """Create a mock edge dict matching kalshalyst output schema."""
    return {
        "ticker": ticker,
        "title": title,
        "estimated_probability": 0.65,
        "yes_price": 55,
        "confidence": confidence,
        "effective_edge_pct": effective_edge,
        "direction": direction,
        "is_sports": is_sports,
        "spread": 3,
    }


def _make_kelly_result(contracts=5, cost_usd=25.0):
    """Create a mock Kelly sizing result matching the expected object shape."""
    result = MagicMock()
    result.contracts = contracts
    result.cost_usd = cost_usd
    result.kelly_fraction = 0.05
    result.fractional_kelly = 0.025
    result.reason = "ok"
    return result


SPORTS_EDGE = _make_mock_edge(
    "KXCBB-26MAR13-TAMU", "Texas A&M vs Oklahoma College Baseball",
    is_sports=True, effective_edge=10.0
)

POLITICAL_EDGE = _make_mock_edge(
    "KXSHUTDOWN-43D", "Government shutdown at least 43 days",
    is_sports=False, effective_edge=8.0
)


class TestSportsEdgeBlocked:
    """Sports edges must be skipped, not executed."""

    def test_sports_edge_skipped_in_loop(self):
        """An edge with is_sports=True must be skipped."""
        from auto_trader import auto_execute_edges

        edges = [SPORTS_EDGE]
        cfg = {}
        auto_cfg = {
            "min_edge_threshold_pct": 3.5,
            "max_daily_loss_usd": 50.0,
            "max_concurrent_positions": 8,
            "max_portfolio_exposure_usd": 200.0,
            "bankroll_usd": 100.0,
        }

        mock_client = MagicMock()

        with patch("auto_trader.get_balance", return_value=100.0), \
             patch("auto_trader.get_current_positions", return_value={}), \
             patch("auto_trader.get_portfolio_exposure", return_value=0.0), \
             patch("auto_trader.get_daily_pnl", return_value=0.0):
            result = auto_execute_edges(mock_client, edges, cfg, auto_cfg, dry_run=True)

        assert result["trades_executed"] == 0, \
            f"CRITICAL: Sports edge was executed! Result: {result}"
        assert result["trades_skipped"] >= 1, \
            f"Sports edge was not counted as skipped: {result}"

    def test_mixed_edges_only_sports_blocked(self):
        """In a mixed list, sports edges get blocked while political passes through."""
        from auto_trader import auto_execute_edges

        edges = [
            SPORTS_EDGE,
            POLITICAL_EDGE,
            _make_mock_edge("KXNHL-GAME", "NHL hockey game", is_sports=True),
        ]
        cfg = {}
        auto_cfg = {
            "min_edge_threshold_pct": 3.5,
            "max_daily_loss_usd": 50.0,
            "max_concurrent_positions": 8,
            "max_portfolio_exposure_usd": 200.0,
            "bankroll_usd": 100.0,
        }

        mock_client = MagicMock()
        kelly_result = _make_kelly_result()

        with patch("auto_trader.get_balance", return_value=100.0), \
             patch("auto_trader.get_current_positions", return_value={}), \
             patch("auto_trader.get_portfolio_exposure", return_value=0.0), \
             patch("auto_trader.get_daily_pnl", return_value=0.0), \
             patch("kelly_size.kelly_size", return_value=kelly_result):
            result = auto_execute_edges(mock_client, edges, cfg, auto_cfg, dry_run=True)

        # 2 sports edges should be skipped
        assert result["trades_skipped"] >= 2, \
            f"Expected at least 2 sports skips, got: {result}"

    def test_all_sports_list_zero_executed(self):
        """A list of ONLY sports edges should result in zero executions."""
        from auto_trader import auto_execute_edges

        edges = [
            _make_mock_edge("KXNFL-GAME1", "NFL Sunday game", is_sports=True),
            _make_mock_edge("KXNBA-FINALS", "NBA Finals game 7", is_sports=True),
            _make_mock_edge("KXMLB-WS", "World Series game", is_sports=True),
        ]
        cfg = {}
        auto_cfg = {
            "min_edge_threshold_pct": 3.5,
            "max_daily_loss_usd": 50.0,
            "max_concurrent_positions": 8,
            "max_portfolio_exposure_usd": 200.0,
            "bankroll_usd": 100.0,
        }

        mock_client = MagicMock()

        with patch("auto_trader.get_balance", return_value=100.0), \
             patch("auto_trader.get_current_positions", return_value={}), \
             patch("auto_trader.get_portfolio_exposure", return_value=0.0), \
             patch("auto_trader.get_daily_pnl", return_value=0.0):
            result = auto_execute_edges(mock_client, edges, cfg, auto_cfg, dry_run=True)

        assert result["trades_executed"] == 0, \
            f"CRITICAL: Sports trades were executed from all-sports list: {result}"
        assert result["trades_skipped"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
