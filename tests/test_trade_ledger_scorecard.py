"""Regression tests for ledger confirmation state and month scorecard."""

import sys
from datetime import datetime, timezone
from pathlib import Path


KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))


def test_record_trade_and_update_confirmation(tmp_path):
    import trade_ledger

    trade_ledger.LEDGER_PATH = tmp_path / "trade_ledger.json"

    record = trade_ledger.record_trade(
        ticker="KXTEST",
        side="yes",
        contracts=5,
        price_cents=55,
        cost_usd=2.75,
        edge_pct=7.0,
        confidence=0.8,
        dry_run=False,
        title="Test market",
    )

    updated = trade_ledger.update_trade_confirmation(
        record["id"],
        confirmation_status="confirmed",
        details="confirmed via portfolio API",
    )

    ledger = trade_ledger.get_ledger()
    assert updated is True
    assert ledger[0]["confirmation_status"] == "confirmed"
    assert "portfolio API" in ledger[0]["confirmation_details"]


def test_monthly_scorecard_uses_closed_entries(tmp_path):
    import trade_ledger

    trade_ledger.LEDGER_PATH = tmp_path / "trade_ledger.json"
    month_now = datetime(2026, 3, 13, tzinfo=timezone.utc)

    ledger_entries = [
        {
            "id": "1",
            "timestamp": "2026-03-02T10:00:00+00:00",
            "ticker": "WINNER",
            "title": "Winner trade",
            "side": "yes",
            "contracts": 5,
            "price_cents": 45,
            "cost_usd": 2.25,
            "edge_pct": 8.0,
            "confidence": 0.7,
            "order_id": "",
            "dry_run": False,
            "status": "closed",
            "confirmation_status": "confirmed",
            "confirmation_checked_at": "2026-03-02T10:01:00+00:00",
            "confirmation_details": "confirmed",
            "close_timestamp": "2026-03-03T10:00:00+00:00",
            "close_reason": "resolved",
            "pnl": 3.5,
        },
        {
            "id": "2",
            "timestamp": "2026-03-04T10:00:00+00:00",
            "ticker": "LOSER",
            "title": "Loser trade",
            "side": "no",
            "contracts": 4,
            "price_cents": 40,
            "cost_usd": 1.60,
            "edge_pct": 5.0,
            "confidence": 0.6,
            "order_id": "",
            "dry_run": False,
            "status": "closed",
            "confirmation_status": "confirmed",
            "confirmation_checked_at": "2026-03-04T10:01:00+00:00",
            "confirmation_details": "confirmed",
            "close_timestamp": "2026-03-05T10:00:00+00:00",
            "close_reason": "resolved",
            "pnl": -1.0,
        },
    ]
    trade_ledger._write_ledger(ledger_entries)

    scorecard = trade_ledger.get_monthly_scorecard(now=month_now)

    assert scorecard["wins"] == 1
    assert scorecard["losses"] == 1
    assert scorecard["total_pnl"] == 2.5
    assert scorecard["edge_accuracy_pct"] == 50.0
    assert scorecard["best_trade"]["ticker"] == "WINNER"
    assert scorecard["worst_trade"]["ticker"] == "LOSER"
