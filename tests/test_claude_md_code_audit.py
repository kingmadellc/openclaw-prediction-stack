"""Executable audit for code-path claims documented in ~/CLAUDE.md."""

from pathlib import Path


HOME = Path.home()
CLAUDE_MD = HOME / "CLAUDE.md"
SKILLS = HOME / "skills"
PREDICTION_MARKET_ANALYST = HOME / "prediction-market-analyst"
PROMPT_LAB = HOME / "prompt-lab"


def read(path: Path) -> str:
    return path.read_text()


def test_claude_md_exists():
    assert CLAUDE_MD.exists()


def test_production_architecture_prompt_loader_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    estimator = read(SKILLS / "kalshalyst" / "scripts" / "claude_estimator.py")

    assert "_load_system_prompt()" in claude_md
    assert "def _load_system_prompt()" in estimator
    assert 'Path.home() / "prompt-lab" / "prompt.md"' in estimator


def test_production_architecture_kelly_loader_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    kelly = read(SKILLS / "kalshalyst" / "scripts" / "kelly_size.py")

    assert "_load_kelly_config()" in claude_md
    assert "def _load_kelly_config()" in kelly
    assert 'Path.home() / "kelly_config.json"' in kelly
    assert 'Path.home() / "prompt-lab" / "kelly_config.json"' in kelly


def test_sports_hard_block_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    kalshalyst = read(SKILLS / "kalshalyst" / "scripts" / "kalshalyst.py")
    auto_trader = read(SKILLS / "kalshalyst" / "scripts" / "auto_trader.py")

    assert "Phase 1 `_is_sports()` now issues `continue`" in claude_md
    assert "HARD BLOCK: never pass sports markets downstream" in kalshalyst
    assert 'edge.get("is_sports", False)' in auto_trader
    assert '"sports_blocked"' in auto_trader


def test_claude_estimator_fallback_chain_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    estimator = read(SKILLS / "kalshalyst" / "scripts" / "claude_estimator.py")

    assert "Fallback = Anthropic API" in claude_md
    assert "Estimator chain: Claude CLI" in estimator
    assert "def _claude_api_estimate(" in estimator
    assert "def _qwen_fallback_batch(" in estimator


def test_kalshalyst_xpulse_and_sports_claims_match_code():
    claude_md = read(CLAUDE_MD)
    kalshalyst = read(SKILLS / "kalshalyst" / "scripts" / "kalshalyst.py")

    assert "Fixed stale variable bug (`prompt` → `xpulse_prompt`)" in claude_md
    assert "xpulse_prompt" in claude_md  # documented claim exists
    assert "_SPORTS_TICKER_PREFIXES" in kalshalyst
    assert "KXWBC" in kalshalyst
    assert "KXCBB" in kalshalyst
    assert "KXCFB" in kalshalyst
    assert "KXWNBA" in kalshalyst
    assert '"indian wells"' in kalshalyst
    assert '"1+ goals"' in kalshalyst


def test_sports_estimator_claims_match_code_and_prompt_lab():
    claude_md = read(CLAUDE_MD)
    sports_estimator = read(SKILLS / "kalshalyst" / "scripts" / "sports_estimator.py")
    eval_sports = read(PROMPT_LAB / "eval_sports.py")
    build_backtest = read(PROMPT_LAB / "build_sports_backtest.py")

    assert "NOT PRODUCTION-READY" in claude_md
    assert "NOT PRODUCTION-READY" in sports_estimator
    assert 'Path.home() / "sports_estimator_config.json"' in sports_estimator
    assert "_find_comp_a_market" in eval_sports
    assert "comp_a_ticker" in build_backtest
    assert "comp_a_verified" in build_backtest


def test_tty_fix_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    estimator = read(SKILLS / "kalshalyst" / "scripts" / "claude_estimator.py")

    assert "start_new_session=True" in claude_md
    assert "start_new_session=True" in estimator


def test_prediction_market_analyst_env_var_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    analyst = read(PREDICTION_MARKET_ANALYST / "src" / "analyst.ts")

    assert "analyst.ts line 11 reads `ANTHROPIC_API_KEY`" in claude_md
    assert "process.env.ANTHROPIC_API_KEY" in analyst


def test_portfolio_api_empty_cursor_claim_matches_code():
    claude_md = read(CLAUDE_MD)
    command_center = read(SKILLS / "kalshi-command-center" / "scripts" / "kalshi_commands.py")
    drift_monitor = read(SKILLS / "portfolio-drift-monitor" / "scripts" / "portfolio_drift.py")

    assert "cursor" in claude_md
    assert "_EMPTY_ONLY_KEYS = {\"cursor\"}" in command_center
    assert "_EMPTY_ONLY_KEYS = {\"cursor\"}" in drift_monitor


def test_fail_loud_order_reconciliation_is_present():
    command_center = read(SKILLS / "kalshi-command-center" / "scripts" / "kalshi_commands.py")

    assert "def _reconcile_order(" in command_center
    assert "I don't know if the order stuck" in command_center
    assert "RECONCILED:" in command_center
