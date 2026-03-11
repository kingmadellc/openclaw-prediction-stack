#!/usr/bin/env python3
"""
Portfolio Drift Monitor for Kalshi

Monitors Kalshi portfolio positions for significant drift (position changes).
Alerts when any position moves beyond configured threshold percentage.

Environment variables:
  KALSHI_KEY_ID: API key ID from dev.kalshi.com
  KALSHI_KEY_PATH: Path to Kalshi private key file (PEM format)
  PORTFOLIO_DRIFT_THRESHOLD: Percentage change to trigger alert (default: 5.0)
  PORTFOLIO_DRIFT_INTERVAL: Minutes between checks for rate limiting (default: 60)

State file:
  ~/.openclaw/state/portfolio_snapshot.json - Stores last known portfolio state
"""

import os
import json
import sys
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple

try:
    from kalshi_python import KalshiClient
except ImportError:
    print("ERROR: kalshi_python package not found. Install with: pip install kalshi_python")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# State File Recovery Helpers
# ──────────────────────────────────────────────────────────────────────────────

def safe_load_state(filepath: Path, default: Any = None) -> Any:
    """Load JSON state file with corruption recovery.

    Tries to load primary file first, falls back to .bak if primary is corrupted.

    Args:
        filepath: Path to JSON state file
        default: Default value if both files fail or don't exist

    Returns:
        Loaded data, or default if unable to load
    """
    bak = filepath.with_suffix('.json.bak')

    # Try primary file first
    if filepath.exists():
        try:
            with open(filepath) as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"WARNING: Primary state file corrupted ({filepath}): {e}")

    # Try backup file
    if bak.exists():
        try:
            with open(bak) as f:
                data = json.load(f)
            print(f"RECOVERED: Loaded backup state from {bak}")
            return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"WARNING: Backup state file also corrupted ({bak}): {e}")

    # Return default
    default_value = default if default is not None else {}
    return default_value


def safe_save_state(filepath: Path, data: Any) -> None:
    """Save JSON state with backup rotation.

    Before writing new state, copies current file to .bak for recovery.

    Args:
        filepath: Path to JSON state file
        data: Data to save
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    bak = filepath.with_suffix('.json.bak')

    # Rotate backup: current → backup
    if filepath.exists():
        try:
            shutil.copy2(filepath, bak)
        except IOError as e:
            print(f"WARNING: Failed to create backup {bak}: {e}")

    # Write new primary file
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"ERROR: Failed to save state to {filepath}: {e}")


class PortfolioDriftMonitor:
    """Monitors Kalshi portfolio drift with rate limiting and threshold alerts."""

    def __init__(self):
        """Initialize monitor with configuration from environment."""
        self.key_id = os.getenv("KALSHI_KEY_ID")
        self.key_path = os.getenv("KALSHI_KEY_PATH")
        self.threshold_pct = float(os.getenv("PORTFOLIO_DRIFT_THRESHOLD", "5.0"))
        self.interval_minutes = int(os.getenv("PORTFOLIO_DRIFT_INTERVAL", "60"))

        # Validate credentials
        if not self.key_id or not self.key_path:
            raise ValueError(
                "KALSHI_KEY_ID and KALSHI_KEY_PATH environment variables required"
            )

        if not os.path.exists(self.key_path):
            raise FileNotFoundError(f"Kalshi key file not found: {self.key_path}")

        # State file location
        self.state_dir = Path.home() / ".openclaw" / "state"
        self.state_file = self.state_dir / "portfolio_snapshot.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Kalshi client
        try:
            self.client = KalshiClient(
                key_id=self.key_id,
                key_path=self.key_path,
                base_url="https://api.kalshi.com/trade-api/v2"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Kalshi client: {e}")

    def get_current_portfolio(self) -> Dict[str, Any]:
        """
        Fetch current portfolio from Kalshi API.

        Returns:
            Dict with portfolio metadata and positions indexed by market symbol
        """
        try:
            response = self.client.get_portfolio()

            # Extract positions and index by market symbol
            positions = {}
            if response and "positions" in response:
                for position in response["positions"]:
                    market_symbol = position.get("market_ticker", "unknown")
                    positions[market_symbol] = {
                        "side": position.get("side", "unknown"),  # "YES" or "NO"
                        "shares": float(position.get("shares", 0)),
                        "avg_price": float(position.get("avg_price", 0)),
                        "pnl": float(position.get("pnl", 0)),
                        "pnl_percent": float(position.get("pnl_percent", 0)),
                        "risk": float(position.get("risk", 0)),
                        "timestamp": datetime.utcnow().isoformat()
                    }

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "positions": positions,
                "total_positions": len(positions)
            }
        except Exception as e:
            raise RuntimeError(f"Failed to fetch portfolio from Kalshi: {e}")

    def load_portfolio_snapshot(self) -> Dict[str, Any]:
        """
        Load last saved portfolio snapshot with corruption recovery.

        Returns:
            Previous portfolio state, or empty dict if no snapshot exists
        """
        return safe_load_state(self.state_file, default={})

    def save_portfolio_snapshot(self, portfolio: Dict[str, Any]) -> None:
        """
        Save current portfolio as baseline for next check with backup rotation.

        Args:
            portfolio: Current portfolio state from get_current_portfolio()
        """
        safe_save_state(self.state_file, portfolio)

    def should_check_now(self, last_snapshot: Dict[str, Any]) -> bool:
        """
        Check if enough time has elapsed for next check (rate limiting).

        Args:
            last_snapshot: Previous portfolio state

        Returns:
            True if interval has elapsed or no previous snapshot, False otherwise
        """
        if not last_snapshot or "timestamp" not in last_snapshot:
            return True

        try:
            last_time = datetime.fromisoformat(last_snapshot["timestamp"])
            elapsed = datetime.utcnow() - last_time
            return elapsed >= timedelta(minutes=self.interval_minutes)
        except Exception:
            return True

    def calculate_drift(self, current: Dict[str, Any], previous: Dict[str, Any]) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Compare current and previous positions to detect drift.

        Args:
            current: Current portfolio from get_current_portfolio()
            previous: Previous portfolio snapshot

        Returns:
            List of (symbol, percent_change, details) tuples for positions exceeding threshold
        """
        current_pos = current.get("positions", {})
        prev_pos = previous.get("positions", {})

        drifted = []

        # Check all positions (current and previous)
        all_symbols = set(current_pos.keys()) | set(prev_pos.keys())

        for symbol in all_symbols:
            curr = current_pos.get(symbol, {})
            prev = prev_pos.get(symbol, {})

            # Calculate changes in key metrics
            changes = {}
            max_drift = 0.0

            # Shares drift
            curr_shares = curr.get("shares", 0)
            prev_shares = prev.get("shares", 0)
            if prev_shares != 0:
                share_drift = abs((curr_shares - prev_shares) / prev_shares * 100)
                changes["shares"] = (curr_shares - prev_shares, share_drift)
                max_drift = max(max_drift, share_drift)

            # P&L drift
            curr_pnl = curr.get("pnl", 0)
            prev_pnl = prev.get("pnl", 0)
            if prev_pnl != 0:
                pnl_drift = abs((curr_pnl - prev_pnl) / prev_pnl * 100)
                changes["pnl"] = (curr_pnl - prev_pnl, pnl_drift)
                max_drift = max(max_drift, pnl_drift)

            # Price drift (avg entry)
            curr_price = curr.get("avg_price", 0)
            prev_price = prev.get("avg_price", 0)
            if prev_price != 0:
                price_drift = abs((curr_price - prev_price) / prev_price * 100)
                changes["price"] = (curr_price - prev_price, price_drift)
                max_drift = max(max_drift, price_drift)

            # Flag if exceeds threshold
            if max_drift >= self.threshold_pct:
                drifted.append((symbol, max_drift, {
                    "current": curr,
                    "previous": prev,
                    "changes": changes
                }))

        return drifted

    def format_drift_alert(self, symbol: str, drift_pct: float, details: Dict[str, Any]) -> str:
        """
        Format drift detection as readable alert.

        Args:
            symbol: Market symbol
            drift_pct: Percentage change
            details: Position details with current/previous/changes

        Returns:
            Formatted alert string with emoji indicators
        """
        curr = details.get("current", {})
        prev = details.get("previous", {})
        changes = details.get("changes", {})

        # Determine direction
        curr_pnl = curr.get("pnl", 0)
        prev_pnl = prev.get("pnl", 0)
        direction_emoji = "📈" if curr_pnl >= prev_pnl else "📉"
        arrow = "↑" if curr_pnl >= prev_pnl else "↓"

        # Side indicator
        side = curr.get("side", "?")

        # Build change details
        change_strs = []

        if "pnl" in changes:
            pnl_change, _ = changes["pnl"]
            change_strs.append(f"{arrow}${abs(pnl_change):.0f} P&L")

        if "shares" in changes:
            share_change, _ = changes["shares"]
            change_strs.append(f"{arrow}{abs(share_change):.0f} shares")

        change_detail = ", ".join(change_strs) if change_strs else "position change"

        # Calculate minutes since last check
        try:
            prev_time = datetime.fromisoformat(prev.get("timestamp", ""))
            minutes_ago = int((datetime.utcnow() - prev_time).total_seconds() / 60)
            time_str = f"Last check: {minutes_ago} minutes ago"
        except Exception:
            time_str = "Last check: unknown time"

        return f"{direction_emoji} {side}/{symbol} → +{drift_pct:.1f}% ({change_detail})\n   {time_str}"

    def run(self) -> None:
        """Execute portfolio drift check and output alerts."""
        # Load previous snapshot
        previous_snapshot = self.load_portfolio_snapshot()

        # Check rate limit
        if not self.should_check_now(previous_snapshot):
            try:
                prev_time = datetime.fromisoformat(previous_snapshot["timestamp"])
                elapsed = datetime.utcnow() - prev_time
                remaining = self.interval_minutes - int(elapsed.total_seconds() / 60)
                print(f"Rate limited: next check in {remaining} minutes")
            except Exception:
                print("Rate limited: check again soon")
            return

        # Fetch current portfolio
        try:
            current_portfolio = self.get_current_portfolio()
        except Exception as e:
            print(f"ERROR: {e}")
            return

        # Handle empty portfolio
        if current_portfolio.get("total_positions", 0) == 0:
            print("Portfolio is empty — no positions to monitor")
            self.save_portfolio_snapshot(current_portfolio)
            return

        # First run: establish baseline
        if not previous_snapshot:
            print(f"✅ Baseline established: {current_portfolio['total_positions']} positions recorded")
            self.save_portfolio_snapshot(current_portfolio)
            return

        # Detect drift
        drifted_positions = self.calculate_drift(current_portfolio, previous_snapshot)

        if drifted_positions:
            print("🚨 Portfolio Drift Alert\n")
            for symbol, drift_pct, details in drifted_positions:
                print(self.format_drift_alert(symbol, drift_pct, details))

            print("\n---")
            stable_count = current_portfolio["total_positions"] - len(drifted_positions)
            if stable_count > 0:
                stable_symbols = [
                    s for s in current_portfolio["positions"].keys()
                    if not any(s == sym for sym, _, _ in drifted_positions)
                ]
                print(f"✓ Stable ({stable_count}): {', '.join(stable_symbols[:5])}")
        else:
            print(f"✓ No drift detected ({current_portfolio['total_positions']} positions stable)")

        # Update snapshot for next check
        self.save_portfolio_snapshot(current_portfolio)


def main():
    """Entry point."""
    try:
        monitor = PortfolioDriftMonitor()
        monitor.run()
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
