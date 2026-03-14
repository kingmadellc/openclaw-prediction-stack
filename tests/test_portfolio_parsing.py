"""Test that portfolio_command() handles every known API response shape.

These tests would have caught the SCHEMA DRIFT crash on March 13, 2026.
The API returned {"cursor": "..."} with no position keys, and portfolio_command()
returned an error string instead of showing an empty portfolio.
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add command center scripts to path
CMD_CENTER_PATH = Path(__file__).parent.parent / "kalshi-command-center" / "scripts"
sys.path.insert(0, str(CMD_CENTER_PATH))


# ── Mock API responses (every shape Kalshi has returned) ─────────────────

CURSOR_ONLY_RESPONSE = '{"cursor": "abc123"}'

EMPTY_POSITIONS_V3 = '{"event_positions": [], "cursor": ""}'

EMPTY_POSITIONS_V2 = '{"market_positions": [], "cursor": ""}'

ONE_POSITION_V3 = json.dumps({
    "event_positions": [{
        "ticker": "KXSHUTDOWN-43D",
        "position_fp": "50",
        "market_exposure_dollars": 49.42,
    }],
    "cursor": ""
})

ONE_POSITION_V2 = json.dumps({
    "market_positions": [{
        "ticker": "KXSHUTDOWN-43D",
        "position": 50,
        "market_exposure_dollars": 49.42,
    }],
    "cursor": ""
})


def _make_mock_client(positions_json: str, balance_cents: int = 22100):
    """Create a mock Kalshi client that returns the given positions JSON."""
    client = MagicMock()

    # Balance response
    balance_resp = MagicMock()
    balance_resp.balance = balance_cents
    client._portfolio_api.get_balance.return_value = balance_resp

    # Positions response
    pos_resp = MagicMock()
    pos_resp.read.return_value = positions_json.encode()
    client._portfolio_api.get_positions_without_preload_content.return_value = pos_resp

    # Market lookup for position details
    market_resp = MagicMock()
    market_resp.read.return_value = json.dumps({
        "market": {"yes_bid": 70, "yes_ask": 75, "last_price": 73}
    }).encode()
    client.call_api.return_value = market_resp

    return client


class TestPortfolioCursorOnly:
    """The exact bug: API returns {"cursor": "..."} and nothing else."""

    def test_cursor_only_does_not_crash(self):
        """portfolio_command() must not return SCHEMA DRIFT error on cursor-only."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(CURSOR_ONLY_RESPONSE)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        assert "SCHEMA DRIFT" not in result, \
            "REGRESSION: cursor-only response still triggers SCHEMA DRIFT error"

    def test_cursor_only_shows_balance(self):
        """Even with no positions, balance should display."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(CURSOR_ONLY_RESPONSE, balance_cents=4775)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        # Should show cash balance somewhere
        assert "47.75" in result or "47.7" in result, \
            f"Balance not shown in output: {result}"


class TestPortfolioV3Response:
    """API v3 returns event_positions."""

    def test_empty_v3_response(self):
        """Empty event_positions list should not crash."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(EMPTY_POSITIONS_V3)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        assert "SCHEMA DRIFT" not in result
        assert "Failed" not in result

    def test_one_position_v3(self):
        """Single position in v3 format should display."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(ONE_POSITION_V3)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        assert "KXSHUTDOWN" in result, f"Position ticker not in output: {result}"


class TestPortfolioV2Response:
    """API v2 returns market_positions."""

    def test_empty_v2_response(self):
        """Empty market_positions list should not crash."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(EMPTY_POSITIONS_V2)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        assert "SCHEMA DRIFT" not in result

    def test_one_position_v2(self):
        """Single position in v2 format should display."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(ONE_POSITION_V2)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        assert "KXSHUTDOWN" in result, f"Position ticker not in output: {result}"


class TestPortfolioNeverReturnsSchemaError:
    """No known API shape should trigger SCHEMA DRIFT."""

    @pytest.mark.parametrize("response_json,name", [
        (CURSOR_ONLY_RESPONSE, "cursor_only"),
        (EMPTY_POSITIONS_V3, "empty_v3"),
        (EMPTY_POSITIONS_V2, "empty_v2"),
        (ONE_POSITION_V3, "one_pos_v3"),
        (ONE_POSITION_V2, "one_pos_v2"),
    ])
    def test_no_schema_drift_error(self, response_json, name):
        """No known response shape should trigger SCHEMA DRIFT."""
        from kalshi_commands import portfolio_command

        mock_client = _make_mock_client(response_json)

        with patch("kalshi_commands._get_client", return_value=mock_client), \
             patch("kalshi_commands._check_enabled", return_value=None):
            result = portfolio_command()

        assert "SCHEMA DRIFT" not in result, \
            f"SCHEMA DRIFT triggered on {name}: {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
