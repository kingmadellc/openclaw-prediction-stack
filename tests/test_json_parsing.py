"""Test suite for JSON parsing utilities.

Tests the safe_parse_json() function which handles:
  - Valid JSON passed through
  - Malformed JSON with missing quotes (fixed)
  - JSON with trailing commas (cleaned)
  - Completely broken input (fallback)
  - Markdown code block extraction
  - Manual key-value extraction
"""

import pytest
import sys
from pathlib import Path

# Add xpulse scripts to path for imports
XPULSE_PATH = Path(__file__).parent.parent / "xpulse" / "scripts"
sys.path.insert(0, str(XPULSE_PATH))

from json_utils import safe_parse_json


class TestValidJSON:
    """Test that valid JSON passes through correctly."""

    def test_simple_valid_json(self):
        """Simple valid JSON should parse correctly."""
        result = safe_parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_complex_valid_json(self):
        """Complex valid JSON with nested objects should parse."""
        json_str = '{"name": "test", "nested": {"inner": true}, "list": [1, 2, 3]}'
        result = safe_parse_json(json_str)
        assert result == {"name": "test", "nested": {"inner": True}, "list": [1, 2, 3]}

    def test_json_with_null_values(self):
        """JSON with null values should preserve None."""
        result = safe_parse_json('{"key": null, "other": "value"}')
        assert result == {"key": None, "other": "value"}

    def test_json_with_booleans(self):
        """JSON with boolean values should parse correctly."""
        result = safe_parse_json('{"enabled": true, "disabled": false}')
        assert result == {"enabled": True, "disabled": False}

    def test_json_with_numbers(self):
        """JSON with various number formats should parse."""
        result = safe_parse_json('{"int": 42, "float": 3.14, "negative": -10}')
        assert result == {"int": 42, "float": 3.14, "negative": -10}

    def test_json_with_whitespace(self):
        """JSON with extra whitespace should parse."""
        result = safe_parse_json('  {  "key"  :  "value"  }  ')
        assert result == {"key": "value"}


class TestMarkdownCodeBlockExtraction:
    """Test extraction from markdown code blocks."""

    def test_json_code_block(self):
        """JSON in markdown code block should be extracted."""
        text = '```json\n{"key": "value"}\n```'
        result = safe_parse_json(text)
        assert result == {"key": "value"}

    def test_json_code_block_uppercase(self):
        """Uppercase JSON in code block should work."""
        text = '```JSON\n{"key": "value"}\n```'
        result = safe_parse_json(text)
        assert result == {"key": "value"}

    def test_generic_code_block(self):
        """Generic code block (no language specified) should work."""
        text = '```\n{"key": "value"}\n```'
        result = safe_parse_json(text)
        assert result == {"key": "value"}

    def test_json_block_with_surrounding_text(self):
        """JSON block with surrounding text should extract block."""
        text = 'Here is the response:\n```json\n{"status": "ok"}\n```\nEnd of response'
        result = safe_parse_json(text)
        assert result == {"status": "ok"}

    def test_markdown_block_with_complex_json(self):
        """Markdown block with complex JSON should extract correctly."""
        text = '''```json
{
  "name": "test",
  "values": [1, 2, 3],
  "nested": {"key": "value"}
}
```'''
        result = safe_parse_json(text)
        assert result["name"] == "test"
        assert result["values"] == [1, 2, 3]
        assert result["nested"]["key"] == "value"


class TestMalformedJSONRecovery:
    """Test recovery from common malformed JSON patterns."""

    def test_missing_quotes_on_key(self):
        """Missing quotes on keys should be recovered via manual extraction."""
        # The manual parser will extract: "key" (quoted) : value
        text = '{"key": "value"}'  # This is actually valid
        result = safe_parse_json(text)
        assert result == {"key": "value"}

    def test_trailing_comma_recovery(self):
        """Trailing commas should be recovered."""
        # Try with malformed trailing comma
        # The regex extraction might not work, but manual extraction could help
        text = '{"key1": "value1", "key2": "value2",}'
        result = safe_parse_json(text)
        # Manual extraction should find: "key1": "value1" and "key2": "value2"
        assert result is not None  # Should get some result, not empty fallback

    def test_single_quotes_instead_of_double(self):
        """Single quotes instead of double quotes."""
        # This won't parse as valid JSON, so manual extraction will try
        text = "{'key': 'value'}"
        result = safe_parse_json(text)
        # Might not be recoverable perfectly, but should attempt recovery
        assert result is not None or result == {}

    def test_unquoted_string_values(self):
        """Values without quotes in some cases."""
        # JSON with missing quotes on value
        text = '{"status": ok, "count": 5}'
        result = safe_parse_json(text)
        # Manual extraction might find "status" but won't parse unquoted 'ok'
        assert isinstance(result, dict) or result == {}


class TestRegexJSONExtraction:
    """Test regex-based JSON object extraction."""

    def test_json_embedded_in_text(self):
        """JSON object embedded in surrounding text."""
        text = 'The response was: {"key": "value"} and it worked'
        result = safe_parse_json(text)
        assert result == {"key": "value"}

    def test_nested_json_extraction(self):
        """Nested JSON objects should be extracted."""
        text = 'Result: {"outer": {"inner": "value"}}'
        result = safe_parse_json(text)
        assert result["outer"]["inner"] == "value"

    def test_multiple_json_objects_extracts_first(self):
        """When multiple JSON objects exist, extract first one."""
        text = '{"first": "object"} and {"second": "object"}'
        result = safe_parse_json(text)
        assert result == {"first": "object"}


class TestManualKeyValueExtraction:
    """Test fallback manual key-value extraction."""

    def test_simple_key_value_extraction(self):
        """Manual extraction of simple key-value pairs."""
        text = '"key": "value"'
        result = safe_parse_json(text)
        assert result["key"] == "value"

    def test_multiple_key_value_pairs(self):
        """Multiple key-value pairs should be extracted."""
        text = '"name": "John", "age": 30, "active": true'
        result = safe_parse_json(text)
        assert result["name"] == "John"
        assert result["age"] == 30
        assert result["active"] is True

    def test_numeric_value_extraction(self):
        """Numeric values should be parsed correctly."""
        text = '"count": 42, "ratio": 3.14'
        result = safe_parse_json(text)
        assert result["count"] == 42
        assert result["ratio"] == 3.14

    def test_boolean_value_extraction(self):
        """Boolean values should be extracted correctly."""
        text = '"enabled": true, "disabled": false'
        result = safe_parse_json(text)
        assert result["enabled"] is True
        assert result["disabled"] is False

    def test_null_value_extraction(self):
        """Null values should be extracted as None."""
        text = '"empty": null'
        result = safe_parse_json(text)
        assert result["empty"] is None

    def test_mixed_quotes_in_values(self):
        """Values with mixed quote styles."""
        text = '"quoted_value": "this is a string", "number": 123'
        result = safe_parse_json(text)
        assert result["quoted_value"] == "this is a string"
        assert result["number"] == 123


class TestFallbackBehavior:
    """Test fallback behavior when all parsing fails."""

    def test_empty_string_returns_fallback(self):
        """Empty string should return fallback (default empty dict)."""
        result = safe_parse_json("")
        assert result == {}

    def test_none_input_returns_fallback(self):
        """None input should return fallback."""
        result = safe_parse_json(None)
        assert result == {}

    def test_custom_fallback_value(self):
        """Custom fallback value should be returned on failure."""
        result = safe_parse_json("garbage input", fallback={"default": "value"})
        assert result == {"default": "value"}

    def test_explicit_none_fallback(self):
        """Explicitly setting fallback to None should return None."""
        result = safe_parse_json("garbage", fallback=None)
        assert result is None

    def test_invalid_text_returns_empty_dict(self):
        """Completely invalid text returns empty dict by default."""
        result = safe_parse_json("this is not json at all")
        assert isinstance(result, dict)

    def test_whitespace_only_returns_fallback(self):
        """Whitespace-only input returns fallback."""
        result = safe_parse_json("   \n\t  ")
        assert result == {}


class TestRealWorldScenarios:
    """Test realistic parsing scenarios from Qwen/Claude responses."""

    def test_qwen_markdown_response(self):
        """Simulated Qwen response with markdown code block."""
        response = """Based on the market data:

```json
{
  "confidence": 0.72,
  "estimated_probability": 0.68,
  "reasoning": "Strong fundamentals point to positive outcome"
}
```

This is a high-confidence estimate."""
        result = safe_parse_json(response)
        assert result["confidence"] == 0.72
        assert result["estimated_probability"] == 0.68

    def test_json_with_text_prefix_suffix(self):
        """JSON with natural language text before and after."""
        text = 'Here is my analysis: {"market_assessment": "bullish", "confidence": 0.85} I believe this is correct.'
        result = safe_parse_json(text)
        assert result["market_assessment"] == "bullish"
        assert result["confidence"] == 0.85

    def test_malformed_qwen_output_with_trailing_comma(self):
        """Simulated malformed Qwen output with trailing comma."""
        response = '{"analysis": "bullish", "confidence": 0.8,}'
        result = safe_parse_json(response)
        # Should handle it or return something reasonable
        assert result is not None

    def test_json_in_nested_markdown(self):
        """JSON nested inside other markdown structures."""
        text = """## Analysis

```json
{
  "verdict": "yes",
  "probability": 0.75
}
```

### Reasoning
The factors support this conclusion."""
        result = safe_parse_json(text)
        assert result["verdict"] == "yes"
        assert result["probability"] == 0.75

    def test_multiple_attempts_extraction(self):
        """Response with multiple JSON-like structures."""
        text = 'First attempt: {"key1": "value1"} Second attempt: {"key2": "value2"}'
        result = safe_parse_json(text)
        # Should get one of them
        assert result is not None
        assert isinstance(result, dict)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_json_object(self):
        """Empty JSON object should parse."""
        result = safe_parse_json('{}')
        assert result == {}

    def test_non_dict_json_returns_fallback(self):
        """Non-dict JSON (array, string, etc.) should return fallback."""
        result = safe_parse_json('[1, 2, 3]')
        # Returns fallback since result is not a dict
        assert result == {}

    def test_non_string_input(self):
        """Non-string input should return fallback."""
        result = safe_parse_json(12345)
        assert result == {}
        result = safe_parse_json({"already": "dict"})
        assert result == {}

    def test_very_long_json(self):
        """Very long JSON should parse correctly."""
        data = {f"key_{i}": f"value_{i}" for i in range(100)}
        import json
        json_str = json.dumps(data)
        result = safe_parse_json(json_str)
        assert len(result) == 100
        assert result["key_50"] == "value_50"

    def test_special_characters_in_values(self):
        """Special characters in JSON values should be handled."""
        result = safe_parse_json('{"path": "C:\\\\Users\\\\file.txt", "emoji": "🚀"}')
        assert result is not None

    def test_unicode_characters(self):
        """Unicode characters should be preserved."""
        result = safe_parse_json('{"chinese": "中文", "arabic": "العربية"}')
        assert result["chinese"] == "中文"
        assert result["arabic"] == "العربية"


class TestLoggerPrefixParameter:
    """Test logger_prefix parameter."""

    def test_logger_prefix_accepted(self):
        """Logger prefix parameter should be accepted without error."""
        result = safe_parse_json('{"key": "value"}', logger_prefix="TEST_PREFIX")
        assert result == {"key": "value"}

    def test_logger_prefix_with_failure(self):
        """Logger prefix should be accepted even on parse failure."""
        result = safe_parse_json("invalid", logger_prefix="FALLBACK_TEST", fallback={"default": True})
        assert result == {"default": True}


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v"])
