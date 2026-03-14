"""Regression tests for post-trade reconciliation."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


CMD_CENTER_PATH = Path(__file__).parent.parent / "kalshi-command-center" / "scripts"
sys.path.insert(0, str(CMD_CENTER_PATH))


def test_reconcile_order_accepts_resting_order():
    from kalshi_commands import _reconcile_order

    mock_client = MagicMock()
    before_positions = {"KXTEST": 0}

    with patch("kalshi_commands._fetch_resting_orders", return_value=[{"order_id": "abc"}]), \
         patch("kalshi_commands._fetch_position_snapshot", return_value={"KXTEST": 0}):
        verified, message = _reconcile_order(
            mock_client,
            action="buy",
            ticker="KXTEST",
            side="yes",
            quantity=5,
            order_id="abc",
            before_positions=before_positions,
            status="resting",
        )

    assert verified is True
    assert "RECONCILED" in message


def test_reconcile_order_fails_loud_when_delta_never_appears():
    from kalshi_commands import _reconcile_order

    mock_client = MagicMock()
    before_positions = {"KXTEST": 0}

    with patch("kalshi_commands._fetch_resting_orders", return_value=[]), \
         patch("kalshi_commands._fetch_position_snapshot", return_value={"KXTEST": 0}), \
         patch("kalshi_commands.time.sleep", return_value=None):
        verified, message = _reconcile_order(
            mock_client,
            action="buy",
            ticker="KXTEST",
            side="yes",
            quantity=5,
            order_id="abc",
            before_positions=before_positions,
            status="executed",
        )

    assert verified is False
    assert "I don't know" in message
