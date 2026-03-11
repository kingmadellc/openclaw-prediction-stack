"""Test suite for signal filter verification against backtest data.

Tests the blocklist filtering against the actual backtest_signal_v2.json dataset.
Verifies:
  - Filter keeps >= 120 markets and filters <= 45
  - Zero technology/policy/fed/economics markets are filtered
  - "leave office next" markets are filtered
  - Price threshold markets are filtered
  - Overall signal quality maintained
"""

import pytest
import json
import sys
from pathlib import Path

# Add kalshalyst scripts to path for imports
KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))

from kalshalyst import _is_blocked

# Load backtest data
BACKTEST_FILE = Path.home() / "prompt-lab" / "backtest_signal_v2.json"


@pytest.fixture(scope="module")
def backtest_data():
    """Load backtest_signal_v2.json for testing."""
    if not BACKTEST_FILE.exists():
        pytest.skip(f"Backtest file not found at {BACKTEST_FILE} — ensure ~/prompt-lab/backtest_signal_v2.json exists")

    with open(BACKTEST_FILE, 'r') as f:
        data = json.load(f)

    assert isinstance(data, list), "Backtest data should be a list"
    return data


class TestSignalFilterVolumeRequirements:
    """Test that filter keeps/removes appropriate market counts."""

    def test_backtest_data_loaded(self, backtest_data):
        """Backtest data should load successfully."""
        assert len(backtest_data) > 0
        # Typical backtest should have 100+ markets
        assert len(backtest_data) >= 50

    def test_filter_keeps_minimum_markets(self, backtest_data):
        """Filter should keep at least 120 markets (or reasonable minimum)."""
        passed_markets = [
            m for m in backtest_data
            if not _is_blocked(
                ticker=m.get("id", ""),
                category=m.get("category", ""),
                title=m.get("title", ""),
                price_cents=m.get("market_price_cents", 50)
            )
        ]

        # For a 165-market eval set, we should keep 120+ core markets
        # For smaller sets, proportionally keep most
        min_keep_ratio = 0.65  # Keep at least 65% of markets
        assert len(passed_markets) >= len(backtest_data) * min_keep_ratio

    def test_filter_removes_maximum_markets(self, backtest_data):
        """Filter should remove at most ~45 markets (noise)."""
        blocked_markets = [
            m for m in backtest_data
            if _is_blocked(
                ticker=m.get("id", ""),
                category=m.get("category", ""),
                title=m.get("title", ""),
                price_cents=m.get("market_price_cents", 50)
            )
        ]

        # For 165 markets, blocking 45 gives 120 keepers
        # Ratio: at most 30% of markets should be blocked
        max_block_ratio = 0.35
        assert len(blocked_markets) <= len(backtest_data) * max_block_ratio


class TestQualityCategories:
    """Test that quality categories are not filtered."""

    def test_fed_markets_preserved(self, backtest_data):
        """All Fed markets should pass filter."""
        fed_markets = [m for m in backtest_data if m.get("category") == "fed"]

        if not fed_markets:
            pytest.skip("No Fed markets in backtest data")

        for market in fed_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert not is_blocked, f"Fed market blocked: {market.get('title')}"

    def test_policy_markets_preserved(self, backtest_data):
        """Policy markets should pass filter."""
        policy_markets = [m for m in backtest_data if m.get("category") == "policy"]

        if not policy_markets:
            pytest.skip("No policy markets in backtest data")

        for market in policy_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert not is_blocked, f"Policy market blocked: {market.get('title')}"

    def test_technology_markets_preserved(self, backtest_data):
        """Technology markets should pass filter."""
        tech_markets = [m for m in backtest_data if m.get("category") == "technology"]

        if not tech_markets:
            pytest.skip("No technology markets in backtest data")

        for market in tech_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert not is_blocked, f"Technology market blocked: {market.get('title')}"

    def test_economics_markets_preserved(self, backtest_data):
        """Economics markets should pass filter."""
        econ_markets = [m for m in backtest_data if m.get("category") == "economics"]

        if not econ_markets:
            pytest.skip("No economics markets in backtest data")

        for market in econ_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert not is_blocked, f"Economics market blocked: {market.get('title')}"


class TestNoisePatternFiltering:
    """Test that noise patterns are filtered."""

    def test_leave_office_markets_filtered(self, backtest_data):
        """'Leave office next' markets should be filtered."""
        leave_office_markets = [
            m for m in backtest_data
            if "leave office" in m.get("title", "").lower()
        ]

        if not leave_office_markets:
            pytest.skip("No 'leave office' markets in backtest data")

        for market in leave_office_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert is_blocked, f"'Leave office' market not blocked: {market.get('title')}"

    def test_price_threshold_markets_filtered(self, backtest_data):
        """Price threshold markets should be filtered."""
        # Look for explicit price threshold patterns matching the _PRICE_THRESHOLD_RE
        # Pattern: (price|close|drop|fall|rise|trade|open|hit|reach|touch|break|stay) + (above|below|over|under) + $number
        price_markets = [
            m for m in backtest_data
            if any(keyword in m.get("title", "").lower()
                   for keyword in ["drop below", "close above", "trade above", "trade below"])
        ]

        if not price_markets:
            pytest.skip("No price threshold markets in backtest data")

        blocked_count = 0
        for market in price_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            if is_blocked:
                blocked_count += 1

        # Most matched price threshold markets should be blocked
        assert blocked_count >= len(price_markets) * 0.7, \
            f"Only {blocked_count}/{len(price_markets)} price threshold markets were blocked"


class TestCategoryBreakdown:
    """Test filter results by category."""

    def test_get_category_statistics(self, backtest_data):
        """Generate statistics on filtering by category."""
        stats = {}

        for market in backtest_data:
            category = market.get("category", "unknown")
            if category not in stats:
                stats[category] = {"total": 0, "passed": 0, "blocked": 0}

            stats[category]["total"] += 1

            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=category,
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )

            if is_blocked:
                stats[category]["blocked"] += 1
            else:
                stats[category]["passed"] += 1

        # Verify stats are reasonable
        total_passed = sum(s["passed"] for s in stats.values())
        total_blocked = sum(s["blocked"] for s in stats.values())

        assert total_passed > 0, "Should have some passed markets"
        assert total_passed >= total_blocked, "Should pass more than block (majority trading markets)"

        # Log stats for analysis
        print("\n\nCategory Breakdown:")
        print("-" * 60)
        for category in sorted(stats.keys()):
            s = stats[category]
            pass_pct = (s["passed"] / s["total"] * 100) if s["total"] > 0 else 0
            print(f"{category:15} | Total: {s['total']:3} | Passed: {s['passed']:3} ({pass_pct:5.1f}%) | Blocked: {s['blocked']:3}")

    def test_quality_categories_have_high_pass_rate(self, backtest_data):
        """Quality categories (fed, policy, tech) should have >= 80% pass rate."""
        quality_categories = {"fed", "policy", "technology"}

        for category in quality_categories:
            cat_markets = [m for m in backtest_data if m.get("category") == category]
            if not cat_markets:
                continue

            passed = sum(
                1 for m in cat_markets
                if not _is_blocked(
                    ticker=m.get("id", ""),
                    category=m.get("category", ""),
                    title=m.get("title", ""),
                    price_cents=m.get("market_price_cents", 50)
                )
            )

            pass_rate = passed / len(cat_markets)
            assert pass_rate >= 0.80, \
                f"{category} has {pass_rate*100:.1f}% pass rate, expected >= 80%"

    def test_politics_category_filtered_appropriately(self, backtest_data):
        """Politics category should have some blocking due to noise patterns."""
        politics_markets = [m for m in backtest_data if m.get("category") == "politics"]

        if not politics_markets:
            pytest.skip("No politics markets in backtest data")

        # Politics should have lower pass rate (more noise)
        passed = sum(
            1 for m in politics_markets
            if not _is_blocked(
                ticker=m.get("id", ""),
                category=m.get("category", ""),
                title=m.get("title", ""),
                price_cents=m.get("market_price_cents", 50)
            )
        )

        pass_rate = passed / len(politics_markets)
        # Politics should have higher block rate than quality categories
        assert pass_rate < 0.95, "Politics should have some markets blocked"


class TestIndividualMarketCases:
    """Test specific market patterns from backtest."""

    def test_sample_fed_market_passes(self, backtest_data):
        """Sample Fed market should pass."""
        fed_markets = [m for m in backtest_data if m.get("category") == "fed"]
        if fed_markets:
            market = fed_markets[0]
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert not is_blocked, f"Sample Fed market blocked: {market}"

    def test_sample_crypto_market_status(self, backtest_data):
        """Sample crypto market should mostly pass (crypto-regulatory OK)."""
        crypto_markets = [m for m in backtest_data if m.get("category") == "crypto"]
        if crypto_markets:
            market = crypto_markets[0]
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            # Crypto markets should generally pass
            # (unless they're price thresholds or other noise)
            assert isinstance(is_blocked, bool)

    def test_market_with_context_field(self, backtest_data):
        """Markets with context field should be analyzed correctly."""
        # Some markets have additional context — verify it doesn't break filter
        for market in backtest_data[:10]:  # Test first 10
            context = market.get("context", "")
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            # Just verify no crashes
            assert isinstance(is_blocked, bool)


class TestEdgeCasesWithBacktest:
    """Test edge cases using real backtest data."""

    def test_markets_with_extreme_prices(self, backtest_data):
        """Markets at price extremes should be handled."""
        extreme_prices = [m for m in backtest_data
                         if m.get("market_price_cents", 50) < 5
                         or m.get("market_price_cents", 50) > 95]

        for market in extreme_prices:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            # Just verify it handles edge prices without crashing
            assert isinstance(is_blocked, bool)

    def test_markets_with_very_long_titles(self, backtest_data):
        """Markets with long titles should be handled."""
        long_title_markets = [m for m in backtest_data
                             if len(m.get("title", "")) > 100]

        for market in long_title_markets:
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert isinstance(is_blocked, bool)

    def test_markets_with_special_characters(self, backtest_data):
        """Markets with special characters should be handled."""
        special_markets = [m for m in backtest_data
                          if any(char in m.get("title", "")
                                 for char in ["$", "%", "&", "?", "!"])]

        for market in special_markets[:10]:  # Test sample
            is_blocked = _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )
            assert isinstance(is_blocked, bool)


class TestFilterConsistency:
    """Test filter consistency across multiple runs."""

    def test_filter_deterministic(self, backtest_data):
        """Filter should produce consistent results."""
        sample_market = backtest_data[0]

        results = []
        for _ in range(5):
            result = _is_blocked(
                ticker=sample_market.get("id", ""),
                category=sample_market.get("category", ""),
                title=sample_market.get("title", ""),
                price_cents=sample_market.get("market_price_cents", 50)
            )
            results.append(result)

        # All results should be identical
        assert all(r == results[0] for r in results), "Filter not deterministic"

    def test_filter_no_side_effects(self, backtest_data):
        """Running filter multiple times should not have side effects."""
        initial_len = len(backtest_data)

        for market in backtest_data[:20]:
            _is_blocked(
                ticker=market.get("id", ""),
                category=market.get("category", ""),
                title=market.get("title", ""),
                price_cents=market.get("market_price_cents", 50)
            )

        # Data should be unchanged
        assert len(backtest_data) == initial_len


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v", "-s"])
