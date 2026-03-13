# OpenClaw Prediction Stack Test Suite

<!-- CODEX: updated test inventory after adding setup, cache-contract, and doc-consistency coverage. -->
Core test coverage for the OpenClaw Prediction Stack's critical functions. **153 passing tests** across seven test modules covering blocklist filtering, JSON parsing, Kelly Criterion sizing, signal quality verification, setup validation, cache contracts, and doc consistency.

## Quick Start

```bash
# Install pytest (one-time)
python3 -m pip install pytest

# Run all tests
python3 -m pytest . -v

# Run specific test module
python3 -m pytest test_blocklist.py -v
python3 -m pytest test_json_parsing.py -v
python3 -m pytest test_kelly.py -v
python3 -m pytest test_signal_filter.py -v
python3 -m pytest test_validate_setup.py -v
python3 -m pytest test_cache_contracts.py -v
python3 -m pytest test_docs_consistency.py -v

# Run with output capture (shows print statements)
python3 -m pytest . -v -s
```

## Test Modules

### 1. test_blocklist.py (36 tests)
**Tests Kalshalyst market filtering functions: `_is_blocked()` and `_is_noise_market()`**

Critical three-layer filter verification:
- **Ticker blocking**: Weather, entertainment, streaming, celebrity markets blocked
- **Category blocking**: Sports, streaming, celebrities excluded
- **Signal quality gates**: Price thresholds, politics noise, coinflips at midrange prices

**Key test classes:**
- `TestWeatherAndEntertainmentBlocking`: Ticker prefix blocklist verification
- `TestPriceThresholdBlocking`: Price threshold pattern detection (e.g., "Bitcoin below $50k")
- `TestPoliticsNoiseBlocking`: Obscure election patterns, margin of victory, "leave office" markets
- `TestCoinflipPatternBlocking`: IPO timing, "when will" patterns at 40-60¢ midrange
- `TestCleanMarketsPass`: Fed, policy, tech, economics markets pass filter
- `TestMicroTimeframeBlocking`: Sub-hourly markets excluded
- `TestEdgeCases`: Case insensitivity, price boundaries, empty inputs
- `TestIntegration`: Multi-layer filter interaction

**Example test:**
```python
# Markets with "leave office next" pattern are blocked
assert _is_noise_market("Will Biden leave office next year?") == "politics_noise"

# Fed rate decision markets pass
assert _is_blocked("FED-RATE-MAY", category="fed", title="Will Fed cut rates?") is False

# IPO timing at midrange price blocked (coinflip pattern)
assert _is_noise_market("When will IPO occur?", price_cents=50) == "coinflip_ipo"
```

---

### 2. test_json_parsing.py (43 tests)
**Tests JSON parsing utilities: `safe_parse_json()` with multiple fallback strategies**

Handles real-world Qwen/Claude output (markdown blocks, malformed JSON, text wrapping):

**Key test classes:**
- `TestValidJSON`: Standard JSON parsing (simple, nested, with nulls/booleans/numbers)
- `TestMarkdownCodeBlockExtraction`: Extract from ```json...``` blocks
- `TestMalformedJSONRecovery`: Trailing commas, single quotes, missing quotes
- `TestRegexJSONExtraction`: JSON embedded in surrounding text
- `TestManualKeyValueExtraction`: Last-resort fallback parser for "key": value pairs
- `TestFallbackBehavior`: Graceful degradation on complete failure
- `TestRealWorldScenarios`: Qwen/Claude response simulation
- `TestEdgeCases`: Unicode, special characters, very long JSON, non-dict results
- `TestLoggerPrefixParameter`: Debug logging integration

**Parsing strategies (in order):**
1. Direct `json.loads()`
2. Extract from markdown code blocks
3. Regex-find JSON object `{...}`
4. Manual key-value extraction (last resort)
5. Return fallback (default: `{}`)

**Example test:**
```python
# Markdown code block extraction
text = '```json\n{"confidence": 0.72}\n```'
result = safe_parse_json(text)
assert result == {"confidence": 0.72}

# Manual extraction from partial JSON
text = '"key1": "value1", "key2": "value2"'
result = safe_parse_json(text)
assert result["key1"] == "value1"
```

---

### 3. test_kelly.py (38 tests)
**Tests Kelly Criterion position sizing: `kelly_size()` for prediction market trades**

Fractional Kelly with confidence discounting for optimal position sizing:

**Key test classes:**
- `TestBasicPositionSizing`: Positive edge, fair value, threshold edges
- `TestNegativeEdgeHandling`: Negative edges return zero contracts
- `TestConfidenceImpact`: Confidence multiplies position size
- `TestMaxPositionLimits`: Contract caps, cost caps, portfolio exposure limits
- `TestEdgeCases`: Invalid prices, zero/negative bankroll, extreme confidence
- `TestSideParameter`: YES/NO side handling with probability inversion
- `TestAlphaFractionalKelly`: Fractional Kelly multiplier (default α=0.25)
- `TestBankrollFractionCalculation`: Bankroll percentage calculations
- `TestResultMetadata`: KellyResult dataclass fields and reason strings
- `TestConvenienceWrapper`: `kelly_from_edge_result()` helper
- `TestRealWorldScenarios`: Small edges conservative, large edges aggressive

**Core formula:**
```
kelly_f = (p * b - q) / b  (where p=prob, q=1-p, b=odds)
fractional_kelly = kelly_f * α * confidence^2
bet_usd = fractional_kelly * bankroll_usd
```

**Example test:**
```python
# Positive edge on YES side
result = kelly_size(
    estimated_prob=0.62,
    market_price_cents=48,
    confidence=0.68,
    bankroll_usd=200.0,
    side="yes"
)
assert result.contracts > 0

# High confidence increases position
result_high = kelly_size(..., confidence=0.90)
result_low = kelly_size(..., confidence=0.30)
assert result_high.contracts > result_low.contracts

# Portfolio exposure limit enforced
result = kelly_size(
    ...,
    max_portfolio_exposure_usd=100.0,
    current_exposure_usd=90.0  # Only $10 left
)
assert result.cost_usd <= 10.0
```

---

### 4. test_signal_filter.py (20 tests)
**Integration tests verifying filter against actual backtest data: `backtest_signal_v2.json`**

Validates filter behavior across 165+ real markets with eval metrics:

**Key test classes:**
- `TestSignalFilterVolumeRequirements`: Keeps ≥65% (120+ markets), blocks ≤35%
- `TestQualityCategories`: Fed/policy/technology/economics have ≥80% pass rate
- `TestNoisePatternFiltering`: "Leave office" markets and price thresholds blocked
- `TestCategoryBreakdown`: Statistics by category (fed, policy, crypto, politics, etc.)
- `TestIndividualMarketCases`: Sample markets from each category
- `TestEdgeCasesWithBacktest`: Long titles, extreme prices, special characters
- `TestFilterConsistency`: Deterministic results, no side effects

**Backtest data location:**
`~/prompt-lab/backtest_signal_v2.json`

**Example output:**
```
Category Breakdown:
fed             | Total:  14 | Passed:  14 (100.0%) | Blocked:   0
policy          | Total:  15 | Passed:  15 (100.0%) | Blocked:   0
technology      | Total:  12 | Passed:  12 (100.0%) | Blocked:   0
economics       | Total:   8 | Passed:   8 (100.0%) | Blocked:   0
crypto          | Total:  35 | Passed:  33 ( 94.3%) | Blocked:   2
politics        | Total:  50 | Passed:  40 ( 80.0%) | Blocked:  10
markets         | Total:  30 | Passed:  12 ( 40.0%) | Blocked:  18
```

---

### 5. test_validate_setup.py (6 tests)
**Tests setup validation helpers without making live network calls**

Validates the public setup validator's fast-fail behavior and mocked success paths:
- Kalshi validation fails clearly when credentials are incomplete
- Anthropic validation handles missing keys and successful mocked responses
- Ollama validation reports missing models and successful mocked inference

---

### 6. test_cache_contracts.py (6 tests)
**Tests Morning Brief cache compatibility with the runtime skills**

Validates the public cache contract and rendering behavior:
- Freshness checks support both ISO `cached_at` and unix `timestamp`
- Kalshalyst bullish edges render as `YES`
- Arbiter rendering accepts both normalized and legacy cache schemas
- Default Morning Brief cache paths match emitted runtime files

---

### 7. test_docs_consistency.py (4 tests)
**Tests high-signal public documentation invariants**

Guards the repo against the exact drift that previously existed:
- Primary docs stay on the 10-skill stack language
- Public examples use `qwen3:latest` as the default local model
- Cost language no longer claims a zero-cost public reference path
- `OPERATIONS.md` points to the real cache files and regression gate

---

## File Structure

```
tests/
├── __init__.py                 # Package marker
├── pytest.ini                  # Pytest configuration
├── README.md                   # This file
├── test_blocklist.py           # 36 tests: market filtering
├── test_cache_contracts.py     # 6 tests: cache/rendering contract
├── test_docs_consistency.py    # 4 tests: public docs invariants
├── test_json_parsing.py        # 43 tests: JSON parsing utilities
├── test_kelly.py               # 38 tests: position sizing
├── test_signal_filter.py       # 20 tests: backtest validation
└── test_validate_setup.py      # 6 tests: setup validator behavior
```

---

## Running Tests

### Run All Tests
```bash
cd ~/skills/tests
python3 -m pytest . -v
```

### Run Specific Test Class
```bash
python3 -m pytest test_blocklist.py::TestPriceThresholdBlocking -v
python3 -m pytest test_kelly.py::TestConfidenceImpact -v
```

### Run Specific Test
```bash
python3 -m pytest test_blocklist.py::TestCleanMarketsPass::test_fed_rate_decision_passes -v
```

### Run with Output Capture (print statements visible)
```bash
python3 -m pytest . -v -s
```

### Run with Short Traceback
```bash
python3 -m pytest . -v --tb=short
```

### Generate Category Statistics
```bash
python3 -m pytest test_signal_filter.py::TestCategoryBreakdown::test_get_category_statistics -v -s
```

---

## Test Results Summary

**Total: 153 tests, 100% passing**

| Module | Tests | Status |
|--------|-------|--------|
| test_blocklist.py | 36 | ✓ PASS |
| test_cache_contracts.py | 6 | ✓ PASS |
| test_docs_consistency.py | 4 | ✓ PASS |
| test_json_parsing.py | 43 | ✓ PASS |
| test_kelly.py | 38 | ✓ PASS |
| test_signal_filter.py | 20 | ✓ PASS |
| test_validate_setup.py | 6 | ✓ PASS |
| **TOTAL** | **153** | **✓ PASS** |

---

## Key Testing Insights

### Blocklist Filter
- **Precision**: Blocks only confirmed noise patterns (no false positives on quality markets)
- **Recall**: Catches 95%+ of intentional noise (politics, price thresholds, coinflips)
- **Quality preservation**: 100% of Fed/policy/tech markets pass filter

### JSON Parsing
- **Robustness**: Handles markdown, malformed, wrapped, and fallback extraction
- **Real-world**: Tested against Qwen/Claude response patterns
- **Graceful degradation**: Returns fallback rather than crashing

### Kelly Sizing
- **Correctness**: Implements fractional Kelly with confidence discounting
- **Limits**: Enforces hard caps (contracts, cost, portfolio exposure)
- **Sanity checks**: Rejects negative edge, low confidence, invalid prices

### Signal Filter
- **Dataset validation**: 165+ real markets, 8 categories
- **Category strength**: Strong (Fed 100%, policy 100%), weak (politics 80%, markets 40%)
- **Integration**: Filter integrates seamlessly with backtest pipeline

---

## Dependencies

- **Python**: 3.8+
- **pytest**: Latest (installed via `pip install pytest`)
- **kalshalyst.py**: Market filtering functions
- **json_utils.py**: JSON parsing utilities
- **kelly_size.py**: Position sizing functions
- **backtest_signal_v2.json**: Real backtest data (optional, for signal filter tests)

---

## Extending the Test Suite

### Add New Test
```python
# In test_blocklist.py
class TestNewFeature:
    def test_example_case(self):
        """Test description."""
        result = _is_blocked("TICKER", category="policy", title="Example")
        assert result is False
```

### Run New Test
```bash
pytest test_blocklist.py::TestNewFeature::test_example_case -v
```

### Add Pytest Marker
```python
@pytest.mark.slow
def test_expensive_operation():
    pass

# Run marked tests:
pytest -m slow -v
```

---

## Notes

- Tests use absolute imports to handle path setup automatically
- Signal filter tests skip gracefully if backtest data unavailable
- All tests are deterministic and idempotent (safe to run multiple times)
- Test output includes full tracebacks for debugging
- Coverage spans unit, integration, and real-world scenario tests

---

## Contact

For questions or issues with the test suite, refer to:
- Kalshalyst: `~/skills/kalshalyst/scripts/kalshalyst.py`
- Kelly Sizing: `~/skills/kalshalyst/scripts/kelly_size.py`
- JSON Utils: `~/skills/xpulse/scripts/json_utils.py`
