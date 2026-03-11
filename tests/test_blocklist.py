"""Test suite for Kalshalyst blocklist filtering functions.

Tests the core signal-quality gates:
  - _is_blocked(): Three-layer filter (ticker, category, signal quality)
  - _is_noise_market(): Identifies no-edge patterns (politics noise, price thresholds, coinflips)
"""

import pytest
import sys
from pathlib import Path

# Add kalshalyst scripts to path for imports
KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))

from kalshalyst import _is_blocked, _is_noise_market


class TestWeatherAndEntertainmentBlocking:
    """Test that weather, entertainment, sports tickers are blocked."""

    def test_weather_ticker_blocked(self):
        """Weather tickers should be blocked."""
        assert _is_blocked("KXTEMP01", category="weather") is True
        assert _is_blocked("KXRAIN05", category="weather") is True
        assert _is_blocked("KXWIND02") is True
        assert _is_blocked("KXSNOW01") is True

    def test_entertainment_ticker_blocked(self):
        """Entertainment tickers should be blocked."""
        assert _is_blocked("KXMOVIE01") is True
        assert _is_blocked("KXCELEB05") is True
        assert _is_blocked("KXYT01") is True

    def test_streaming_ticker_blocked(self):
        """Streaming and social media tickers should be blocked."""
        assert _is_blocked("KXSTREAM01") is True
        assert _is_blocked("KXTWIT01") is True

    def test_market_ticker_blocked(self):
        """Market index tickers should be blocked."""
        assert _is_blocked("NASDAQ01") is True
        assert _is_blocked("INX01") is True

    def test_entertainment_category_blocked(self):
        """Entertainment categories should be blocked."""
        assert _is_blocked("SomeTicket", category="entertainment") is True
        assert _is_blocked("SomeTicket", category="streaming") is True
        assert _is_blocked("SomeTicket", category="celebrities") is True
        assert _is_blocked("SomeTicket", category="sports") is True

    def test_clean_ticker_passes(self):
        """Non-blocked tickers should pass."""
        assert _is_blocked("POLICY001") is False
        assert _is_blocked("FED-RATE-MAY") is False
        assert _is_blocked("TECH-AI-001") is False


class TestPriceThresholdBlocking:
    """Test that price threshold markets are blocked."""

    def test_bitcoin_price_threshold_blocked(self):
        """Bitcoin price thresholds should be blocked."""
        assert _is_noise_market("Will Bitcoin drop below $50k?") == "price_threshold"
        # "exceed" matches price_asset pattern instead
        assert _is_noise_market("Will Bitcoin exceed $100,000?") == "price_asset"
        assert _is_noise_market("Will BTC trade above $60k?") == "price_threshold"

    def test_stock_price_threshold_blocked(self):
        """Stock price thresholds should be blocked."""
        assert _is_noise_market("Will S&P 500 close above 5000?") == "price_threshold"
        # MSFT matches the asset pattern
        assert _is_noise_market("Will MSFT exceed $400?") == "price_asset"
        assert _is_noise_market("Will Tesla fall below $100?") == "price_threshold"

    def test_commodity_price_threshold_blocked(self):
        """Commodity price thresholds should be blocked."""
        assert _is_noise_market("Will oil close above $80 per barrel?") == "price_threshold"
        assert _is_noise_market("Will gold drop below $1900?") == "price_threshold"

    def test_price_asset_pattern_blocked(self):
        """Asset-specific price patterns should be blocked."""
        # These match the _PRICE_ASSET_RE pattern
        assert _is_noise_market("Will Ethereum be below $2000?") == "price_asset"
        assert _is_noise_market("Will MSFT exceed $400?") == "price_asset"


class TestPoliticsNoiseBlocking:
    """Test that politics noise patterns are blocked."""

    def test_margin_of_victory_blocked(self):
        """Margin of victory markets should be blocked."""
        assert _is_noise_market("Margin of victory in 2024 election") == "politics_noise"
        assert _is_noise_market("Will Trump win by more than 5% margin of victory?") == "politics_noise"

    def test_leave_office_patterns_blocked(self):
        """'Leave office next' patterns should be blocked."""
        assert _is_noise_market("Will Biden leave office next year?") == "politics_noise"
        assert _is_noise_market("Who will leave office first?") == "politics_noise"

    def test_obscure_election_patterns_blocked(self):
        """Obscure election patterns should be blocked."""
        assert _is_noise_market("City council primary 2025") == "politics_noise"
        assert _is_noise_market("State senate runoff") == "politics_noise"
        assert _is_noise_market("Special election in Ohio") == "politics_noise"

    def test_foreign_election_patterns_blocked(self):
        """Foreign election patterns should be blocked."""
        assert _is_noise_market("Dutch election results 2025") == "politics_noise"
        assert _is_noise_market("Brazilian election 2026") == "politics_noise"
        assert _is_noise_market("Japanese election next round") == "politics_noise"

    def test_vote_share_patterns_blocked(self):
        """Vote share and seat count patterns should be blocked."""
        # "vote share" pattern matches politics_noise
        assert _is_noise_market("Will candidate A win vote share above 40%?") == "politics_noise"
        # "How many" at midrange triggers coinflip_uncertain first
        assert _is_noise_market("How many seats in parliament?", price_cents=50) == "coinflip_uncertain"


class TestCoinflipPatternBlocking:
    """Test that coinflip patterns at midrange prices are blocked."""

    def test_ipo_coinflip_at_midrange(self):
        """IPO timing at 40-60¢ should be blocked."""
        assert _is_noise_market("When will company X have its IPO?", price_cents=50) == "coinflip_ipo"
        assert _is_noise_market("Will IPO occur in Q2?", price_cents=45) == "coinflip_ipo"
        assert _is_noise_market("IPO timing by end of year", price_cents=55) == "coinflip_ipo"

    def test_how_many_coinflip_at_midrange(self):
        """'How many' patterns at 40-60¢ should be blocked."""
        assert _is_noise_market("How many seats will party win?", price_cents=50) == "coinflip_uncertain"
        assert _is_noise_market("How many countries will join the alliance?", price_cents=48) == "coinflip_uncertain"

    def test_when_will_coinflip_at_midrange(self):
        """'When will' patterns at 40-60¢ should be blocked."""
        assert _is_noise_market("When will recession occur?", price_cents=50) == "coinflip_uncertain"
        assert _is_noise_market("When will AI achieve AGI?", price_cents=42) == "coinflip_uncertain"

    def test_ipo_at_extreme_price_passes(self):
        """IPO pattern at non-midrange price should NOT trigger coinflip filter."""
        # At 15¢ (strong NO), the IPO pattern doesn't count as coinflip
        assert _is_noise_market("When will company X have its IPO?", price_cents=15) == ""
        # At 85¢ (strong YES), the IPO pattern doesn't count as coinflip
        assert _is_noise_market("When will company X have its IPO?", price_cents=85) == ""

    def test_coinflip_threshold_boundaries(self):
        """Coinflip filter should apply strictly to 40-60¢ range."""
        # Boundary test: 39¢ should pass (outside midrange)
        assert _is_noise_market("When will X happen?", price_cents=39) == ""
        # Boundary test: 61¢ should pass (outside midrange)
        assert _is_noise_market("When will X happen?", price_cents=61) == ""
        # Boundary test: 40¢ should block
        assert _is_noise_market("When will X happen?", price_cents=40) == "coinflip_uncertain"
        # Boundary test: 60¢ should block
        assert _is_noise_market("When will X happen?", price_cents=60) == "coinflip_uncertain"


class TestCleanMarketsPass:
    """Test that clean, tradeable markets pass the filter."""

    def test_fed_rate_decision_passes(self):
        """Fed rate decision markets should pass."""
        assert _is_blocked("FED-RATE-MAY", category="fed", title="Will Federal Reserve cut rates in May?") is False
        assert _is_noise_market("Will Federal Reserve cut rates in May?") == ""

    def test_tech_policy_markets_pass(self):
        """Tech policy markets should pass."""
        assert _is_blocked("TECH-REG-001", category="policy", title="Will TikTok be banned in US?") is False
        assert _is_noise_market("Will TikTok be banned in the US by 2025?") == ""

    def test_crypto_regulation_passes(self):
        """Crypto regulation markets should pass."""
        assert _is_blocked("CRYPTO-REG-001", category="regulation",
                          title="Will SEC approve Bitcoin ETF?") is False
        assert _is_noise_market("Will SEC approve Bitcoin ETF in 2025?") == ""

    def test_economics_markets_pass(self):
        """Economics markets should pass."""
        assert _is_blocked("ECON-GDP-Q1", category="economics",
                          title="Will US GDP grow above 2%?") is False
        assert _is_noise_market("Will US GDP grow above 2% in Q1?") == ""

    def test_ai_policy_markets_pass(self):
        """AI policy markets should pass."""
        assert _is_blocked("AI-POLICY-001", category="technology",
                          title="Will Congress pass AI regulation by 2025?") is False
        assert _is_noise_market("Will Congress pass AI regulation by 2025?") == ""


class TestMicroTimeframeBlocking:
    """Test that micro-timeframe markets are blocked."""

    def test_next_hour_blocked(self):
        """Markets expiring in next hour should be blocked."""
        assert _is_blocked("TEST", title="Will price up in next 15 min?") is True
        assert _is_blocked("TEST", title="Will BTC rise in next 30 minutes?") is True
        assert _is_blocked("TEST", title="Market closes in next hour") is True

    def test_next_hour_variations(self):
        """Various hour/minute patterns should be blocked."""
        assert _is_blocked("TEST", title="Will price go up in next 5 min?") is True
        assert _is_blocked("TEST", title="Will it happen in next 10 min?") is True
        assert _is_blocked("TEST", title="What happens next hour?") is True


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_title(self):
        """Empty title should not crash."""
        assert _is_blocked("TEST", title="") is False
        assert _is_noise_market("") == ""

    def test_case_insensitivity(self):
        """Filters should be case insensitive."""
        assert _is_noise_market("WHEN WILL X HAPPEN?", price_cents=50) == "coinflip_uncertain"
        assert _is_noise_market("Will Bitcoin DROP BELOW $50k?") == "price_threshold"
        assert _is_noise_market("LEAVE OFFICE NEXT YEAR") == "politics_noise"

    def test_default_price_cents(self):
        """Default price_cents should be 50 (midrange)."""
        # When price not specified, defaults to 50
        assert _is_noise_market("When will X happen?") == "coinflip_uncertain"

    def test_price_at_boundaries(self):
        """Test price at exact boundaries."""
        # Price exactly at 40 and 60 should trigger coinflip
        assert _is_noise_market("When will X happen?", price_cents=40) == "coinflip_uncertain"
        assert _is_noise_market("When will X happen?", price_cents=60) == "coinflip_uncertain"
        # Default 50 (midrange) should also trigger
        assert _is_noise_market("When will X happen?") == "coinflip_uncertain"
        # Just outside should not
        assert _is_noise_market("When will X happen?", price_cents=39) == ""
        assert _is_noise_market("When will X happen?", price_cents=61) == ""

    def test_multiple_patterns_in_one_title(self):
        """If title matches multiple patterns, one should be returned."""
        # This title has both margin and leave office patterns
        result = _is_noise_market("Leave office first with margin of victory")
        assert result in ["politics_noise"]  # One of the noise reasons


class TestIntegration:
    """Integration tests combining multiple filter layers."""

    def test_blocklist_with_multiple_conditions(self):
        """Test a market that's blocked by multiple conditions."""
        # KXMOVIE is blocked by ticker AND category might be entertainment
        assert _is_blocked("KXMOVIE01", category="entertainment",
                          title="Will Movie X win Oscar?") is True

    def test_clean_market_passes_all_filters(self):
        """Test a market that passes all filter layers."""
        result = _is_blocked(
            ticker="FED-RATE-MAY2025",
            category="fed",
            title="Will Federal Reserve cut interest rates at May meeting?",
            price_cents=35
        )
        assert result is False

    def test_signal_filter_gate_blocks_before_price_logic(self):
        """Signal quality gate should block regardless of other factors."""
        # This is a price threshold market — should be blocked
        result = _is_blocked(
            ticker="LEGIT-TICKER",
            category="policy",
            title="Will Bitcoin drop below $50k?",
            price_cents=75
        )
        assert result is True

    def test_sports_token_detection(self):
        """Test _is_sports function indirectly through blocklist."""
        # Sports markets get tagged but may still pass initial filter
        from kalshalyst import _is_sports

        assert _is_sports("NFL-DRAFT", "Will QB be #1 pick in NFL draft?") is True
        assert _is_sports("NBA-FINALS", "Will Warriors win NBA championship?") is True
        assert _is_sports("CLEAN-TICKER", "Will Fed cut rates?") is False


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v"])
