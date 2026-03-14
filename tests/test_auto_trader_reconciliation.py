"""Regression tests for auto_trader post-trade reconciliation."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))


def _make_edge():
    return {
        "ticker": "KXTEST",
        "title": "Test market",
        "estimated_probability": 0.65,
        "yes_price": 55,
        "yes_ask": 56,
        "yes_bid": 54,
        "confidence": 0.8,
        "effective_edge_pct": 8.0,
        "direction": "underpriced",
        "is_sports": False,
        "spread": 2,
    }


def _make_kelly_result():
    result = MagicMock()
    result.contracts = 5
    result.cost_usd = 2.80
    result.kelly_fraction = 0.05
    result.fractional_kelly = 0.04
    result.reason = "ok"
    return result


def test_auto_trader_marks_trade_confirmed():
    from auto_trader import auto_execute_edges

    cfg = {}
    auto_cfg = {
        "min_edge_threshold_pct": 3.5,
        "max_daily_loss_usd": 50.0,
        "max_concurrent_positions": 8,
        "max_portfolio_exposure_usd": 200.0,
        "bankroll_usd": 100.0,
        "reconciliation_wait_seconds": 0,
    }

    with patch("auto_trader.get_balance", return_value=100.0), \
         patch("auto_trader.get_current_positions", side_effect=[{}, {"KXTEST": {"position": 5, "side": "yes", "abs_qty": 5}}]), \
         patch("auto_trader.get_portfolio_exposure", return_value=0.0), \
         patch("auto_trader.get_daily_pnl", return_value=0.0), \
         patch("kelly_size.kelly_size", return_value=_make_kelly_result()), \
         patch("auto_trader.record_trade", return_value={"id": "trade-1"}), \
         patch("auto_trader.update_trade_confirmation") as update_confirmation, \
         patch("kalshi_commands._place_order", return_value="✅ Bought 5x YES on KXTEST at 56¢"):
        result = auto_execute_edges(MagicMock(), [_make_edge()], cfg, auto_cfg, dry_run=False)

    assert result["trades_executed"] == 1
    update_confirmation.assert_called_once()
    assert update_confirmation.call_args.kwargs["confirmation_status"] == "confirmed"


def test_auto_trader_marks_trade_unconfirmed_when_delta_missing():
    from auto_trader import auto_execute_edges

    cfg = {}
    auto_cfg = {
        "min_edge_threshold_pct": 3.5,
        "max_daily_loss_usd": 50.0,
        "max_concurrent_positions": 8,
        "max_portfolio_exposure_usd": 200.0,
        "bankroll_usd": 100.0,
        "reconciliation_wait_seconds": 0,
    }

    with patch("auto_trader.get_balance", return_value=100.0), \
         patch("auto_trader.get_current_positions", side_effect=[{}, {}]), \
         patch("auto_trader.get_portfolio_exposure", return_value=0.0), \
         patch("auto_trader.get_daily_pnl", return_value=0.0), \
         patch("kelly_size.kelly_size", return_value=_make_kelly_result()), \
         patch("auto_trader.record_trade", return_value={"id": "trade-2"}), \
         patch("auto_trader.update_trade_confirmation") as update_confirmation, \
         patch("kalshi_commands._place_order", return_value="✅ Bought 5x YES on KXTEST at 56¢"):
        result = auto_execute_edges(MagicMock(), [_make_edge()], cfg, auto_cfg, dry_run=False)

    assert result["trades_executed"] == 0
    assert result["trades_skipped"] == 1
    assert "unconfirmed:KXTEST" in result["errors"]
    assert update_confirmation.call_args.kwargs["confirmation_status"] == "unconfirmed"
