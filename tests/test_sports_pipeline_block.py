"""Test that sports markets are BLOCKED from the trading pipeline.

NOT "does _is_sports() return True" — that's a component test.
This tests: "does a sports market actually get excluded from trading?"

These tests would have caught the $62.56 sports filter bypass on March 13, 2026.
The filter tagged markets as sports but never called `continue` to skip them.
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add kalshalyst scripts to path
KALSHALYST_PATH = Path(__file__).parent.parent / "kalshalyst" / "scripts"
sys.path.insert(0, str(KALSHALYST_PATH))

from kalshalyst import _is_sports, _is_blocked


# ── The 5 positions that bypassed the filter on March 13 ─────────────────

REAL_SPORTS_BYPASSES = [
    ("KXWBC-26MAR14-DR", "Dominican Republic wins by over 3.5 runs"),
    ("KXNHL-26MAR13-EDM-STL", "Edmonton at St. Louis - Adam Henrique 1+ goals"),
    ("KXATP-26MAR13-ZVEREV", "Zverev vs Sinner ATP Indian Wells"),
    ("KXCBB-26MAR13-TAMU-OU", "Texas A&M vs Oklahoma College Baseball"),
    ("KXCBB-26MAR13-MSST-ARK", "Mississippi State vs Arkansas College Baseball"),
]

REAL_POLITICAL_MARKETS = [
    ("KXTRADE-CHINA", "Will Trump make a new free trade agreement with China?"),
    ("KXSHUTDOWN-43D", "How long will the government shutdown last? At least 43 days"),
    ("KXSHUTDOWN-60D", "How long will the government shutdown last? At least 60 days"),
    ("KXLUTNICK-OUT", "Howard Lutnick out as Commerce Secretary?"),
    ("KXADMIN-LEAVE", "Who will leave the Trump administration this year? Howard Lutnick"),
]


class TestSportsDetection:
    """Every sports market that bypassed on March 13 must be detected."""

    @pytest.mark.parametrize("ticker,title", REAL_SPORTS_BYPASSES,
                             ids=["wbc_dominican", "nhl_henrique", "atp_zverev",
                                  "cbb_tamu", "cbb_msstate"])
    def test_real_bypass_detected(self, ticker, title):
        """Each market that leaked $62.56 must now be caught by _is_sports()."""
        assert _is_sports(ticker, title) is True, \
            f"CRITICAL: {ticker} ({title}) would bypass sports filter again"

    @pytest.mark.parametrize("ticker,title", REAL_POLITICAL_MARKETS,
                             ids=["trump_china", "shutdown_43", "shutdown_60",
                                  "lutnick_out", "admin_leave"])
    def test_political_markets_not_flagged(self, ticker, title):
        """Political markets must NOT be caught by sports filter."""
        assert _is_sports(ticker, title) is False, \
            f"FALSE POSITIVE: {ticker} ({title}) incorrectly flagged as sports"


class TestSportsTickerPrefixes:
    """Every known Kalshi sports ticker prefix must be detected."""

    MUST_BLOCK_PREFIXES = [
        "KXNFL", "KXNBA", "KXMLB", "KXNHL", "KXMLS", "KXNCAA", "KXPGA",
        "KXUFC", "KXWWE", "KXSOCCER", "KXTENNIS", "KXATP",
        # Added after March 13 bypass
        "KXWBC", "KXCBB", "KXCFB", "KXWNBA", "KXLPGA", "KXF1",
        "KXNASCAR", "KXCRICKET", "KXRUGBY", "KXBOXING", "KXMMA",
        "KXESPORT",
    ]

    @pytest.mark.parametrize("prefix", MUST_BLOCK_PREFIXES)
    def test_ticker_prefix_detected(self, prefix):
        """Sports ticker prefix must trigger _is_sports()."""
        assert _is_sports(f"{prefix}-ANYEVENT", "Some event title") is True, \
            f"Ticker prefix {prefix} not detected by _is_sports()"


class TestSportsKeywordCoverage:
    """Sports keywords in titles must be detected regardless of ticker."""

    MUST_BLOCK_TITLES = [
        "Who will win the baseball championship?",
        "College basketball tournament results",
        "Will the football team win?",
        "NHL hockey game tonight",
        "Soccer match between teams",
        "Tennis grand slam finals",
        "UFC fight night main event",
        "NBA playoffs game 7",
        "NFL draft first pick",
        "College baseball world series",
        "Indian Wells tennis final",
        "World Baseball Classic semifinal",
        "Total goals scored in match",
        "Player scores 1+ goals tonight",
        "Team wins by over 3.5 runs",
    ]

    @pytest.mark.parametrize("title", MUST_BLOCK_TITLES)
    def test_sports_title_detected(self, title):
        """Sports title must be detected even with clean ticker."""
        assert _is_sports("CLEAN-TICKER", title) is True, \
            f"Sports title not detected: {title}"


class TestFalsePositiveProtection:
    """Political/macro markets must NEVER be flagged as sports."""

    MUST_PASS_TITLES = [
        "Will the Federal Reserve cut interest rates?",
        "Will inflation drop below 3%?",
        "Government shutdown duration",
        "Will Trump sign executive order?",
        "Will Congress pass AI regulation?",
        "Will Bitcoin exceed $100k?",
        "Will TikTok be banned in the US?",
        "Will there be a recession in 2026?",
        "Commander in chief approval rating",  # "commander" contains no sports word
        "Inflation rate for March",  # "inflation" must not match "nfl"
        "GDP growth forecast",
        "Will trade deal with China happen?",
        "Howard Lutnick Commerce Secretary",
    ]

    @pytest.mark.parametrize("title", MUST_PASS_TITLES)
    def test_political_title_not_flagged(self, title):
        """Political/macro title must not be flagged as sports."""
        assert _is_sports("POLICY-TICKER", title) is False, \
            f"FALSE POSITIVE on political market: {title}"


class TestCategoryBlockInteraction:
    """Verify _is_blocked catches sports via category even if _is_sports misses."""

    def test_sports_category_blocked(self):
        """API category='sports' must be hard-blocked."""
        assert _is_blocked("UNKNOWN-TICKER", category="sports",
                           title="Some unknown event") is True

    def test_political_category_passes(self):
        """Political categories must pass."""
        for cat in ["politics", "policy", "economics", "fed", "technology"]:
            assert _is_blocked("POLICY-001", category=cat,
                               title="Will Congress pass a bill?") is False, \
                f"Category '{cat}' incorrectly blocked"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
