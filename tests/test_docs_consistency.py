"""CODEX: high-signal documentation consistency checks for the public repo."""

from pathlib import Path


ROOT = Path(__file__).parent.parent


def read_text(relative_path):
    """Read a repo file as UTF-8 text."""
    return (ROOT / relative_path).read_text()


def test_primary_docs_use_ten_skill_language():
    """CODEX: stack topology should stay consistent across primary docs."""
    root_readme = read_text("README.md")
    setup_readme = read_text("prediction-stack-setup/README.md")
    setup_skill = read_text("prediction-stack-setup/SKILL.md")

    assert "10-skill stack" in root_readme
    assert "Turns the 10-skill stack" in setup_readme
    assert "wires the 10-skill OpenClaw Prediction Market Trading Stack" in setup_skill
    assert "Turns 8 standalone skills" not in setup_readme
    assert "wires the 8 skills" not in setup_skill


def test_primary_docs_use_qwen3_as_default_model():
    """CODEX: public examples and setup docs should agree on the default local model."""
    files = [
        "README.md",
        "xpulse/README.md",
        "xpulse/SKILL.md",
        "xpulse/example-config.yaml",
        "prediction-stack-setup/config.example.yaml",
    ]

    for relative_path in files:
        assert "qwen3:latest" in read_text(relative_path), relative_path


def test_public_cost_language_no_longer_claims_zero_month_reference_path():
    """CODEX: cost language should match the Anthropic-backed reference implementation."""
    root_readme = read_text("README.md")
    kalshalyst_readme = read_text("kalshalyst/README.md")
    setup_readme = read_text("prediction-stack-setup/README.md")

    assert "$0/month" not in root_readme
    assert "Anthropic-backed Claude estimation" in kalshalyst_readme
    assert "Anthropic API spend" in setup_readme


def test_operations_doc_references_actual_cache_files_and_regression_gate():
    """CODEX: the runbook should point operators to the real cache files and tests."""
    operations = read_text("OPERATIONS.md")

    assert "~/.openclaw/state/kalshalyst_cache.json" in operations
    assert "~/.openclaw/state/arbiter_cache.json" in operations
    assert "~/.openclaw/state/x_signal_cache.json" in operations
    assert "python3 -m pytest tests/test_validate_setup.py tests/test_cache_contracts.py tests/test_docs_consistency.py -q" in operations
