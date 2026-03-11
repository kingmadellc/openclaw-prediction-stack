#!/usr/bin/env python3
"""
Auto-Trader — Autonomous Kalshi trading orchestrator.

Bridges kalshalyst edge scanner → Kelly sizing → order execution with
six layers of safety controls. Designed for hands-off operation via launchd.

Usage:
    python3 auto_trader.py [--dry-run] [--force]

Config: ~/.openclaw/auto_trader_config.json
Logs:   ~/.openclaw/logs/auto_trader_state.jsonl
Kill:   Set "enabled": false in config, or:
        sed -i '' 's/"enabled": true/"enabled": false/' ~/.openclaw/auto_trader_config.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] AutoTrader: %(message)s",
)
logger = logging.getLogger("auto_trader")

# ── Paths ─────────────────────────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".openclaw" / "auto_trader_config.json"
STATE_LOG = Path.home() / ".openclaw" / "logs" / "auto_trader_state.jsonl"
TRADE_LOG = Path.home() / ".openclaw" / "logs" / "trades.jsonl"

# ── Sibling imports (add script dir to path) ──────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Import from kalshi-command-center (sibling skill)
KALSHI_CMD_DIR = SCRIPT_DIR.parent.parent / "kalshi-command-center" / "scripts"
sys.path.insert(0, str(KALSHI_CMD_DIR))


# ── Config ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load auto-trader config. Returns empty dict if missing."""
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text())
            logger.info(f"Config loaded (enabled={cfg.get('enabled', False)})")
            return cfg
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
    return {}


# ── State Logging ─────────────────────────────────────────────────────────

def _log_state(event: str, data: dict):
    """Append to auto_trader_state.jsonl."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **data,
    }
    try:
        STATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── Safety Checks ─────────────────────────────────────────────────────────

def get_current_positions(client) -> dict:
    """Fetch current Kalshi positions. Returns {ticker: {position, side}}."""
    positions = {}
    try:
        resp = client._portfolio_api.get_positions_without_preload_content(limit=100)
        data = json.loads(resp.read())
        for p in data.get("market_positions", []):
            ticker = p.get("ticker", "")
            qty = int(p.get("position", 0))
            if qty != 0:
                positions[ticker] = {
                    "position": qty,
                    "side": "yes" if qty > 0 else "no",
                    "abs_qty": abs(qty),
                }
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
    return positions


def get_balance(client) -> float:
    """Get available cash balance in USD."""
    try:
        balance_resp = client._portfolio_api.get_balance()
        return balance_resp.balance / 100.0
    except Exception as e:
        logger.error(f"Failed to fetch balance: {e}")
        return 0.0


def get_daily_pnl() -> float:
    """Sum realized P&L from trade log for today (UTC). Negative = loss."""
    today = datetime.now(timezone.utc).date()
    daily_pnl = 0.0
    try:
        if not TRADE_LOG.exists():
            return 0.0
        with open(TRADE_LOG) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if not ts:
                        continue
                    entry_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                    if entry_date == today and "pnl" in entry:
                        daily_pnl += entry["pnl"]
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass
    return daily_pnl


def get_portfolio_exposure(positions: dict) -> float:
    """Estimate total portfolio exposure in USD from positions."""
    # Each contract costs ~price_cents. Approximate with 50¢ avg if we don't
    # have exact prices. Conservative estimate.
    total = 0.0
    for ticker, pos in positions.items():
        # Rough estimate: each contract ≈ $0.50 average cost
        total += pos["abs_qty"] * 0.50
    return total


# ── Stale Order Cleanup ──────────────────────────────────────────────────────

def cleanup_stale_orders(client, max_age_minutes: int = 60) -> int:
    """Cancel resting orders older than max_age_minutes.

    Args:
        client: Initialized Kalshi API client
        max_age_minutes: Age threshold in minutes (default 60)

    Returns:
        Count of cancelled orders
    """
    cancelled = 0
    try:
        # Fetch all resting orders
        resp = client._portfolio_api.get_orders_without_preload_content(status='resting')
        data = json.loads(resp.read())
        orders = data.get('orders', [])

        if not orders:
            logger.info("No resting orders to clean up")
            return 0

        # Current time in UTC
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(minutes=max_age_minutes)

        logger.info(f"Checking {len(orders)} resting orders for age > {max_age_minutes} minutes")

        for order in orders:
            try:
                order_id = order.get('order_id', '')
                ticker = order.get('ticker', '?')
                created_time_str = order.get('created_time', '')

                if not order_id or not created_time_str:
                    continue

                # Parse ISO format created_time
                created_time = datetime.fromisoformat(created_time_str.replace('Z', '+00:00'))
                age_minutes = (now - created_time).total_seconds() / 60.0

                # If order is older than threshold, cancel it
                if created_time < cutoff_time:
                    logger.info(f"Cancelling stale order {order_id} on {ticker} (age={age_minutes:.1f} min)")

                    # Call DELETE endpoint
                    url = f"https://api.elections.kalshi.com/trade-api/v2/portfolio/orders/{order_id}"
                    client.call_api("DELETE", url)

                    # Log the cancellation
                    _log_state("stale_order_cancelled", {
                        "order_id": order_id,
                        "ticker": ticker,
                        "age_minutes": round(age_minutes, 1),
                    })
                    cancelled += 1

            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to parse order: {e}")
                continue
            except Exception as e:
                logger.warning(f"Failed to cancel order {order.get('order_id', '?')}: {e}")
                continue

        if cancelled > 0:
            logger.info(f"Cleaned up {cancelled} stale orders")
            _log_state("stale_cleanup_complete", {"cancelled": cancelled})

        return cancelled

    except Exception as e:
        logger.error(f"Failed to cleanup stale orders: {e}")
        return 0


# ── Core Execution ────────────────────────────────────────────────────────

def auto_execute_edges(client, edges: list, cfg: dict, auto_cfg: dict, dry_run: bool = False) -> dict:
    """Execute trades for discovered edges with full safety checks.

    Args:
        client: Initialized Kalshi API client
        edges: List of edge dicts from kalshalyst (post-filter)
        cfg: Kalshalyst pipeline config
        auto_cfg: Auto-trader config
        dry_run: If True, log but don't place orders

    Returns:
        Execution summary dict
    """
    from kelly_size import kelly_size

    min_edge = auto_cfg.get("min_edge_threshold_pct", 3.5)
    max_daily_loss = auto_cfg.get("max_daily_loss_usd", 50.0)
    max_positions = auto_cfg.get("max_concurrent_positions", 8)
    max_exposure = auto_cfg.get("max_portfolio_exposure_usd", 200.0)
    bankroll = auto_cfg.get("bankroll_usd", 100.0)

    # ── Pre-flight checks ─────────────────────────────────────────────
    # Balance check
    balance = get_balance(client)
    if balance < 5.0:
        _log_state("abort", {"reason": f"Insufficient balance: ${balance:.2f}"})
        logger.warning(f"Aborting: balance ${balance:.2f} < $5 minimum")
        return {"trades_executed": 0, "trades_skipped": len(edges), "reason": "low_balance"}

    # Daily loss check
    daily_pnl = get_daily_pnl()
    if daily_pnl < -max_daily_loss:
        _log_state("abort", {"reason": f"Daily loss ${daily_pnl:.2f} exceeds limit ${max_daily_loss}"})
        logger.warning(f"Aborting: daily loss ${daily_pnl:.2f} exceeds -${max_daily_loss}")
        return {"trades_executed": 0, "trades_skipped": len(edges), "reason": "daily_loss_limit"}

    # Current positions
    positions = get_current_positions(client)
    num_positions = len(positions)
    exposure = get_portfolio_exposure(positions)

    logger.info(f"Pre-flight: balance=${balance:.2f}, positions={num_positions}, "
                f"exposure~${exposure:.2f}, daily_pnl=${daily_pnl:.2f}")

    # ── Execute edges ─────────────────────────────────────────────────
    executed = 0
    skipped = 0
    errors = []
    remaining_balance = balance
    executed_trades = []  # Track executed trades for alerts

    for edge in edges[:10]:  # Top 10 by edge
        ticker = edge.get("ticker", "")
        title = edge.get("title", "?")[:50]
        est_prob = edge.get("estimated_probability", 0.5)
        market_price = edge.get("yes_price", 50)
        confidence = edge.get("confidence", 0.3)
        effective_edge = edge.get("effective_edge_pct", 0)
        direction = edge.get("direction", "fair")

        # Determine side
        side = "yes" if direction == "underpriced" else "no"

        # ── Skip checks ───────────────────────────────────────────
        # Edge threshold
        if effective_edge < min_edge:
            _log_state("edge_skipped", {"ticker": ticker, "reason": "below_threshold",
                                        "edge": effective_edge, "threshold": min_edge})
            skipped += 1
            continue

        # Duplicate position
        if ticker in positions:
            held_side = positions[ticker]["side"]
            if held_side == side:
                _log_state("edge_skipped", {"ticker": ticker, "reason": "duplicate_position",
                                            "held_side": held_side})
                skipped += 1
                continue

        # Concurrent position limit
        if num_positions + executed >= max_positions:
            _log_state("edge_skipped", {"ticker": ticker, "reason": "max_positions",
                                        "current": num_positions + executed, "limit": max_positions})
            skipped += 1
            continue

        # Portfolio exposure limit
        if exposure >= max_exposure:
            _log_state("edge_skipped", {"ticker": ticker, "reason": "max_exposure",
                                        "exposure": round(exposure, 2), "limit": max_exposure})
            skipped += 1
            continue

        # ── Kelly sizing ──────────────────────────────────────────
        try:
            result = kelly_size(
                estimated_prob=est_prob,
                market_price_cents=market_price,
                confidence=confidence,
                bankroll_usd=min(bankroll, remaining_balance),
                side=side,
                current_exposure_usd=exposure,
                max_portfolio_exposure_usd=max_exposure,
            )
        except Exception as e:
            logger.error(f"Kelly sizing failed for {ticker}: {e}")
            errors.append(f"kelly_error:{ticker}")
            skipped += 1
            continue

        if result.contracts <= 0:
            _log_state("edge_skipped", {"ticker": ticker, "reason": f"kelly_zero: {result.reason}",
                                        "edge": effective_edge})
            skipped += 1
            continue

        # Balance check for this trade
        if result.cost_usd > remaining_balance:
            _log_state("edge_skipped", {"ticker": ticker, "reason": "insufficient_balance",
                                        "cost": result.cost_usd, "available": remaining_balance})
            skipped += 1
            continue

        # ── Execute or dry-run ────────────────────────────────────
        # Determine execution price (use ask for buys)
        exec_price = market_price
        if side == "yes":
            exec_price = edge.get("yes_ask", market_price) or market_price
        else:
            # For NO side, price = 100 - yes_bid
            yes_bid = edge.get("yes_bid", market_price) or market_price
            exec_price = 100 - yes_bid

        if dry_run:
            _log_state("edge_dry_run", {
                "ticker": ticker, "title": title, "side": side,
                "contracts": result.contracts, "cost_usd": round(result.cost_usd, 2),
                "price_cents": exec_price, "edge_pct": effective_edge,
                "kelly_fraction": round(result.fractional_kelly, 4),
                "confidence": confidence,
            })
            logger.info(f"[DRY RUN] {side.upper()} {result.contracts}x {ticker} @ {exec_price}¢ "
                        f"(${result.cost_usd:.2f}, edge={effective_edge:.1f}%)")
            executed_trades.append({
                "ticker": ticker,
                "side": side,
                "contracts": result.contracts,
                "price_cents": exec_price,
                "edge_pct": effective_edge,
                "cost_usd": result.cost_usd,
                "dry_run": True,
            })
            executed += 1
            remaining_balance -= result.cost_usd
            exposure += result.cost_usd
            continue

        # Live execution
        try:
            from kalshi_commands import _place_order, _trade_audit

            order_result = _place_order("buy", ticker, side, result.contracts, exec_price)

            _log_state("edge_executed", {
                "ticker": ticker, "title": title, "side": side,
                "contracts": result.contracts, "cost_usd": round(result.cost_usd, 2),
                "price_cents": exec_price, "edge_pct": effective_edge,
                "kelly_fraction": round(result.fractional_kelly, 4),
                "confidence": confidence,
                "order_result": order_result[:200],
            })

            if "✅" in order_result:
                logger.info(f"EXECUTED: {side.upper()} {result.contracts}x {ticker} @ {exec_price}¢ "
                            f"(${result.cost_usd:.2f}, edge={effective_edge:.1f}%)")
                executed_trades.append({
                    "ticker": ticker,
                    "side": side,
                    "contracts": result.contracts,
                    "price_cents": exec_price,
                    "edge_pct": effective_edge,
                    "cost_usd": result.cost_usd,
                    "dry_run": False,
                })
                executed += 1
                remaining_balance -= result.cost_usd
                exposure += result.cost_usd
            else:
                logger.warning(f"Order issue for {ticker}: {order_result[:100]}")
                errors.append(f"order_issue:{ticker}")
                skipped += 1

        except Exception as e:
            logger.error(f"Execution failed for {ticker}: {e}")
            _log_state("edge_failed", {"ticker": ticker, "error": str(e)[:200]})
            errors.append(f"exec_error:{ticker}")
            skipped += 1

    summary = {
        "trades_executed": executed,
        "trades_skipped": skipped,
        "daily_pnl": round(daily_pnl, 2),
        "portfolio_exposure": round(exposure, 2),
        "balance_remaining": round(remaining_balance, 2),
        "errors": errors,
        "executed_trades": executed_trades,
    }
    return summary


# ── Main Entry Point ──────────────────────────────────────────────────────

def run_auto_trader(dry_run: bool = False) -> dict:
    """Full auto-trading cycle: scan → size → execute."""

    _log_state("scan_start", {"dry_run": dry_run})
    logger.info("=" * 60)
    logger.info(f"Auto-Trader starting (dry_run={dry_run})")
    logger.info("=" * 60)

    # ── Load config ───────────────────────────────────────────────────
    auto_cfg = load_config()
    if not auto_cfg:
        logger.info("No auto_trader_config.json found — exiting")
        _log_state("scan_end", {"reason": "no_config"})
        return {"status": "no_config"}

    if not auto_cfg.get("enabled", False):
        logger.info("Auto-trading disabled in config — exiting")
        _log_state("scan_end", {"reason": "disabled"})
        return {"status": "disabled"}

    if dry_run or auto_cfg.get("dry_run", False):
        dry_run = True
        logger.info("DRY RUN MODE — no orders will be placed")

    # ── Initialize Kalshi client ──────────────────────────────────────
    try:
        from kalshi_commands import _get_client, _check_enabled

        err = _check_enabled()
        if err:
            logger.error(f"Kalshi not configured: {err}")
            _log_state("scan_end", {"reason": "kalshi_not_configured", "error": err})
            return {"status": "error", "error": err}

        client = _get_client()
        if not client:
            logger.error("Failed to connect to Kalshi API")
            _log_state("scan_end", {"reason": "kalshi_connection_failed"})
            return {"status": "error", "error": "connection_failed"}

    except ImportError as e:
        logger.error(f"Cannot import kalshi_commands: {e}")
        _log_state("scan_end", {"reason": "import_error", "error": str(e)})
        return {"status": "error", "error": str(e)}

    # ── Cleanup stale orders ──────────────────────────────────────────
    stale_cleanup_count = cleanup_stale_orders(client, max_age_minutes=60)
    logger.info(f"Stale order cleanup: {stale_cleanup_count} orders cancelled")

    # ── Run kalshalyst scan ───────────────────────────────────────────
    try:
        from kalshalyst import fetch_kalshi_markets, calculate_edges, _apply_market_filter

        # Default pipeline config
        pipeline_cfg = {
            "min_volume": 50,
            "min_days_to_close": 7,
            "max_days_to_close": 365,
            "max_pages": 3,
            "max_fetch_seconds": 30,
            "max_markets_to_analyze": 30,
            "no_confidence_lo": 0.48,
            "no_confidence_hi": 0.55,
            "min_edge_pct": 3.0,
            "ensemble_enabled": False,
        }

        # Check for ensemble config
        ensemble_cfg_path = Path.home() / ".openclaw" / "config.yaml"
        if ensemble_cfg_path.exists():
            try:
                import yaml
                with open(ensemble_cfg_path) as f:
                    full_cfg = yaml.safe_load(f) or {}
                kalshalyst_cfg = full_cfg.get("kalshalyst", {})
                pipeline_cfg.update(kalshalyst_cfg)
            except Exception:
                pass

        logger.info("Phase 1: Fetching markets...")
        markets = fetch_kalshi_markets(client, pipeline_cfg)
        if not markets:
            logger.info("No markets passed filters")
            _log_state("scan_end", {"reason": "no_markets", "edges_found": 0})
            return {"status": "no_markets"}

        logger.info(f"Phase 3+4: Estimating edges for {len(markets)} markets...")
        edges = calculate_edges(markets, pipeline_cfg)

        logger.info("Phase 4.5: Applying market filter...")
        edges = _apply_market_filter(edges, pipeline_cfg)

        logger.info(f"Found {len(edges)} edges after filtering")

    except Exception as e:
        logger.error(f"Scan failed: {e}")
        _log_state("scan_end", {"reason": "scan_error", "error": str(e)[:200]})
        return {"status": "error", "error": str(e)}

    if not edges:
        logger.info("No edges found — nothing to trade")
        _log_state("scan_end", {"edges_found": 0, "trades_executed": 0})
        return {"status": "no_edges"}

    # ── Execute trades ────────────────────────────────────────────────
    logger.info(f"Phase 6: Auto-executing top edges (dry_run={dry_run})...")
    summary = auto_execute_edges(client, edges, pipeline_cfg, auto_cfg, dry_run=dry_run)

    summary["edges_found"] = len(edges)
    summary["markets_scanned"] = len(markets)

    _log_state("scan_end", summary)
    logger.info(f"Scan complete: {summary['trades_executed']} executed, "
                f"{summary['trades_skipped']} skipped, "
                f"{len(edges)} edges found from {len(markets)} markets")

    logger.info("=" * 60)

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenClaw Auto-Trader")
    parser.add_argument("--dry-run", action="store_true", help="Log but don't place orders")
    parser.add_argument("--force", action="store_true", help="Run even if recently ran")
    args = parser.parse_args()

    result = run_auto_trader(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
