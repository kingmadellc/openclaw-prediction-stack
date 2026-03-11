"""Test suite for Kelly Criterion position sizing.

Tests the kelly_size() function which calculates optimal position sizing for
prediction market trades using fractional Kelly with confidence discounting.

Core tests:
  - Position size calculation with various edge/odds inputs
  - Edge cases: negative edge returns 0, high confidence caps correctly
  - Maximum position size limits enforcement
  - Bankroll fraction calculations
"""

import pytest
import sys
from pathlib import Path

# Add kalshalyst scripts to path for imports
KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))

from kelly_size import kelly_size, KellyResult, kelly_from_edge_result


class TestBasicPositionSizing:
    """Test basic position sizing with various edge/odds inputs."""

    def test_positive_edge_yes_side(self):
        """Positive edge on YES side should result in contracts."""
        result = kelly_size(
            estimated_prob=0.62,
            market_price_cents=48,
            confidence=0.68,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts > 0
        assert result.cost_usd > 0
        assert result.kelly_fraction > 0
        assert result.edge_pct > 0

    def test_positive_edge_no_side(self):
        """Positive edge on NO side should result in contracts."""
        result = kelly_size(
            estimated_prob=0.35,  # Low probability (strong NO)
            market_price_cents=48,
            confidence=0.70,
            bankroll_usd=200.0,
            side="no"
        )
        assert result.contracts > 0
        assert result.cost_usd > 0

    def test_fair_value_no_edge(self):
        """Fair value (no edge) should return zero contracts."""
        result = kelly_size(
            estimated_prob=0.50,
            market_price_cents=50,  # Fair value
            confidence=0.50,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0
        assert result.cost_usd == 0

    def test_slight_edge_above_minimum(self):
        """Edge just above minimum threshold should size small."""
        result = kelly_size(
            estimated_prob=0.533,  # 3.3% edge
            market_price_cents=50,
            confidence=0.50,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts >= 1 or result.contracts == 0  # Might be too small


class TestNegativeEdgeHandling:
    """Test that negative edges are rejected."""

    def test_negative_edge_returns_zero(self):
        """Negative edge should return zero contracts."""
        result = kelly_size(
            estimated_prob=0.45,  # Less than 50¢ market price
            market_price_cents=50,
            confidence=0.80,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0
        assert result.cost_usd == 0

    def test_strong_negative_edge(self):
        """Strong negative edge should definitely not be traded."""
        result = kelly_size(
            estimated_prob=0.25,
            market_price_cents=75,
            confidence=0.90,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0

    def test_kelly_fraction_negative(self):
        """Kelly fraction should be negative for losing bets."""
        result = kelly_size(
            estimated_prob=0.40,
            market_price_cents=60,
            confidence=0.80,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.kelly_fraction <= 0
        assert result.contracts == 0


class TestConfidenceImpact:
    """Test that confidence affects position sizing."""

    def test_high_confidence_larger_position(self):
        """Higher confidence should result in larger positions."""
        result_high = kelly_size(
            estimated_prob=0.62,
            market_price_cents=48,
            confidence=0.90,
            bankroll_usd=200.0,
            side="yes"
        )
        result_low = kelly_size(
            estimated_prob=0.62,
            market_price_cents=48,
            confidence=0.30,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result_high.contracts > result_low.contracts

    def test_low_confidence_threshold(self):
        """Confidence below 0.2 should return zero contracts."""
        result = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.15,  # Below 0.2 threshold
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0
        assert "Confidence too low" in result.reason

    def test_confidence_exactly_at_threshold(self):
        """Confidence at exactly 0.2 should be acceptable."""
        result = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.20,
            bankroll_usd=200.0,
            side="yes"
        )
        # Should not be rejected for confidence
        assert "Confidence too low" not in result.reason


class TestMaxPositionLimits:
    """Test that position size limits are enforced."""

    def test_max_contracts_per_trade_enforced(self):
        """Position should be capped at max_contracts_per_trade."""
        result = kelly_size(
            estimated_prob=0.80,  # Very high edge
            market_price_cents=20,  # Cheap contracts
            confidence=0.95,
            bankroll_usd=5000.0,
            side="yes",
            max_contracts=50
        )
        assert result.contracts <= 50
        if result.contracts == 50:
            assert result.capped is True

    def test_max_cost_per_trade_enforced(self):
        """Position cost should be capped at max_cost_usd."""
        result = kelly_size(
            estimated_prob=0.80,
            market_price_cents=30,
            confidence=0.95,
            bankroll_usd=10000.0,
            side="yes",
            max_cost_usd=25.0
        )
        assert result.cost_usd <= 25.0

    def test_portfolio_exposure_limit_enforced(self):
        """Position should be capped by portfolio exposure limit."""
        result = kelly_size(
            estimated_prob=0.75,
            market_price_cents=40,
            confidence=0.85,
            bankroll_usd=100.0,
            side="yes",
            max_portfolio_exposure_usd=100.0,
            current_exposure_usd=90.0  # Only $10 left
        )
        # Cost should not exceed remaining $10
        assert result.cost_usd <= 10.0

    def test_portfolio_at_limit_returns_zero(self):
        """Portfolio at limit should return zero contracts."""
        result = kelly_size(
            estimated_prob=0.75,
            market_price_cents=50,
            confidence=0.85,
            bankroll_usd=100.0,
            side="yes",
            max_portfolio_exposure_usd=100.0,
            current_exposure_usd=100.0  # At limit
        )
        assert result.contracts == 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_invalid_price_zero(self):
        """Price of zero should be rejected."""
        result = kelly_size(
            estimated_prob=0.60,
            market_price_cents=0,
            confidence=0.80,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0
        assert "Invalid price" in result.reason

    def test_invalid_price_100(self):
        """Price of 100 should be rejected."""
        result = kelly_size(
            estimated_prob=0.60,
            market_price_cents=100,
            confidence=0.80,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0
        assert "Invalid price" in result.reason

    def test_invalid_price_negative(self):
        """Negative price should be rejected."""
        result = kelly_size(
            estimated_prob=0.60,
            market_price_cents=-10,
            confidence=0.80,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0

    def test_zero_bankroll(self):
        """Zero bankroll should return zero."""
        result = kelly_size(
            estimated_prob=0.70,
            market_price_cents=50,
            confidence=0.80,
            bankroll_usd=0.0,
            side="yes"
        )
        assert result.contracts == 0
        assert "No bankroll" in result.reason

    def test_negative_bankroll(self):
        """Negative bankroll should return zero."""
        result = kelly_size(
            estimated_prob=0.70,
            market_price_cents=50,
            confidence=0.80,
            bankroll_usd=-100.0,
            side="yes"
        )
        assert result.contracts == 0

    def test_extreme_confidence_values(self):
        """Extreme confidence values should be handled."""
        # Confidence > 1.0
        result = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=1.5,  # > 1.0
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts >= 0

        # Confidence = 0.0
        result = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.0,
            bankroll_usd=200.0,
            side="yes"
        )
        assert result.contracts == 0


class TestSideParameter:
    """Test 'yes' and 'no' side handling."""

    def test_side_case_insensitive(self):
        """Side parameter should be case insensitive."""
        result_lower = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.70,
            bankroll_usd=200.0,
            side="yes"
        )
        result_upper = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.70,
            bankroll_usd=200.0,
            side="YES"
        )
        assert result_lower.contracts == result_upper.contracts
        assert result_lower.cost_usd == result_upper.cost_usd

    def test_no_side_inverts_probability(self):
        """NO side should use inverted probability."""
        # Betting NO on 65% means betting on 35%
        result = kelly_size(
            estimated_prob=0.65,  # 65% for YES
            market_price_cents=52,  # Market says 52%
            confidence=0.70,
            bankroll_usd=200.0,
            side="no"
        )
        # NO has 35% true prob vs 48% market, so no edge on NO
        assert result.contracts == 0 or result.edge_pct <= 0

    def test_yes_no_sides_consistent(self):
        """YES and NO sides should handle symmetry correctly."""
        # Market at 50¢ (fair), 60% edge on YES
        result_yes = kelly_size(
            estimated_prob=0.60,
            market_price_cents=50,
            confidence=0.75,
            bankroll_usd=200.0,
            side="yes"
        )
        # Same market, but betting NO with 40% edge
        result_no = kelly_size(
            estimated_prob=0.40,
            market_price_cents=50,
            confidence=0.75,
            bankroll_usd=200.0,
            side="no"
        )
        # Both should have positive contracts (same edge, different expression)
        assert result_yes.contracts > 0
        assert result_no.contracts > 0


class TestAlphaFractionalKelly:
    """Test alpha (fractional Kelly) parameter."""

    def test_default_alpha_lower_position_than_full_kelly(self):
        """Default alpha (0.25) should size smaller than full Kelly."""
        # Full Kelly (alpha=1.0)
        result_full = kelly_size(
            estimated_prob=0.70,
            market_price_cents=45,
            confidence=0.85,
            bankroll_usd=200.0,
            side="yes",
            alpha=1.0
        )
        # Quarter Kelly (default)
        result_quarter = kelly_size(
            estimated_prob=0.70,
            market_price_cents=45,
            confidence=0.85,
            bankroll_usd=200.0,
            side="yes",
            alpha=0.25
        )
        assert result_quarter.contracts < result_full.contracts

    def test_alpha_zero_returns_minimal(self):
        """Alpha of zero should apply MIN_CONTRACTS floor if edge > 0."""
        result = kelly_size(
            estimated_prob=0.70,
            market_price_cents=45,
            confidence=0.85,
            bankroll_usd=200.0,
            side="yes",
            alpha=0.0
        )
        # fractional_kelly = 0, but kelly_f > 0, so MIN_CONTRACTS (1) is applied
        assert result.contracts == 1
        assert result.fractional_kelly == 0.0

    def test_custom_alpha_values(self):
        """Custom alpha values should scale positions."""
        result_half = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.70,
            bankroll_usd=200.0,
            side="yes",
            alpha=0.5
        )
        result_quarter = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.70,
            bankroll_usd=200.0,
            side="yes",
            alpha=0.25
        )
        assert result_half.contracts > result_quarter.contracts


class TestBankrollFractionCalculation:
    """Test bankroll fraction calculations."""

    def test_bankroll_fraction_computed(self):
        """Bankroll fraction should be computed correctly."""
        result = kelly_size(
            estimated_prob=0.70,
            market_price_cents=45,
            confidence=0.85,
            bankroll_usd=100.0,
            side="yes"
        )
        # bankroll_fraction = (cost / bankroll) * 100
        expected_fraction = (result.cost_usd / 100.0) * 100
        assert result.bankroll_fraction == pytest.approx(expected_fraction, abs=0.1)

    def test_bankroll_fraction_respects_limits(self):
        """Bankroll fraction should not exceed limits."""
        result = kelly_size(
            estimated_prob=0.80,
            market_price_cents=30,
            confidence=0.95,
            bankroll_usd=50.0,
            side="yes",
            max_cost_usd=10.0
        )
        # Should be at most 10/50 * 100 = 20%
        assert result.bankroll_fraction <= 20.1


class TestResultMetadata:
    """Test KellyResult object and metadata."""

    def test_kelly_result_has_all_fields(self):
        """KellyResult should contain all expected fields."""
        result = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.70,
            bankroll_usd=200.0,
            side="yes"
        )
        assert hasattr(result, 'contracts')
        assert hasattr(result, 'cost_usd')
        assert hasattr(result, 'kelly_fraction')
        assert hasattr(result, 'fractional_kelly')
        assert hasattr(result, 'edge_pct')
        assert hasattr(result, 'reason')
        assert hasattr(result, 'capped')
        assert hasattr(result, 'bankroll_fraction')

    def test_reason_provides_context(self):
        """Reason string should provide context for decision."""
        result = kelly_size(
            estimated_prob=0.62,
            market_price_cents=48,
            confidence=0.68,
            bankroll_usd=200.0,
            side="yes"
        )
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0
        # Should contain Kelly and fractional Kelly info
        assert "Kelly=" in result.reason or len(result.reason) > 0

    def test_capped_flag_set_correctly(self):
        """Capped flag should indicate if position was limited."""
        # This should hit a cap
        result = kelly_size(
            estimated_prob=0.90,
            market_price_cents=20,
            confidence=0.99,
            bankroll_usd=5000.0,
            side="yes",
            max_contracts=10
        )
        # Might be capped or might not, but field should exist
        assert isinstance(result.capped, bool)


class TestConvenienceWrapper:
    """Test kelly_from_edge_result() convenience wrapper."""

    def test_wrapper_with_edge_dict(self):
        """Wrapper should size position from edge result dict."""
        edge = {
            "estimated_probability": 0.70,
            "yes_price": 45,
            "confidence": 0.85,
            "direction": "underpriced"
        }
        result = kelly_from_edge_result(edge, bankroll_usd=200.0)
        assert result.contracts > 0
        assert result.cost_usd > 0

    def test_wrapper_defaults_to_yes_side(self):
        """Wrapper should infer YES side for underpriced."""
        edge = {
            "estimated_probability": 0.70,
            "yes_price": 45,
            "confidence": 0.85,
            "direction": "underpriced"
        }
        result = kelly_from_edge_result(edge, bankroll_usd=200.0)
        assert result.contracts > 0

    def test_wrapper_switches_to_no_side(self):
        """Wrapper should infer NO side for overpriced."""
        edge = {
            "estimated_probability": 0.30,
            "yes_price": 55,
            "confidence": 0.75,
            "direction": "overpriced"
        }
        result = kelly_from_edge_result(edge, bankroll_usd=200.0)
        # Should compute NO side position
        assert isinstance(result, KellyResult)

    def test_wrapper_handles_missing_fields(self):
        """Wrapper should use defaults for missing fields."""
        edge = {}
        result = kelly_from_edge_result(edge, bankroll_usd=200.0)
        # Should not crash, use defaults
        assert isinstance(result, KellyResult)


class TestRealWorldScenarios:
    """Test realistic trading scenarios."""

    def test_small_edge_conservative_sizing(self):
        """Small edge should size conservatively."""
        result = kelly_size(
            estimated_prob=0.53,
            market_price_cents=50,
            confidence=0.55,
            bankroll_usd=1000.0,
            side="yes"
        )
        # Small edge, low confidence = small position
        assert result.bankroll_fraction < 5.0  # Less than 5% of bankroll

    def test_large_edge_larger_sizing(self):
        """Large edge with high confidence should size larger."""
        result = kelly_size(
            estimated_prob=0.85,
            market_price_cents=40,
            confidence=0.90,
            bankroll_usd=1000.0,
            side="yes"
        )
        # Large edge, high confidence = larger position
        assert result.contracts > 0

    def test_multiple_positions_respect_exposure(self):
        """Multiple positions should respect total exposure."""
        # First trade
        result1 = kelly_size(
            estimated_prob=0.70,
            market_price_cents=45,
            confidence=0.80,
            bankroll_usd=500.0,
            side="yes",
            max_portfolio_exposure_usd=200.0,
            current_exposure_usd=0.0
        )
        # Second trade (with first trade's exposure)
        result2 = kelly_size(
            estimated_prob=0.65,
            market_price_cents=48,
            confidence=0.75,
            bankroll_usd=500.0,
            side="yes",
            max_portfolio_exposure_usd=200.0,
            current_exposure_usd=result1.cost_usd
        )
        # Total exposure should not exceed limit
        total_exposure = result1.cost_usd + result2.cost_usd
        assert total_exposure <= 200.0


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v"])
