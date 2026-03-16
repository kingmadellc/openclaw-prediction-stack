"""CODEX: contract tests for prediction-stack-setup/scripts/validate_setup.py."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parent.parent
VALIDATE_SETUP_PATH = ROOT / "prediction-stack-setup" / "scripts" / "validate_setup.py"


def load_validate_setup_module():
    """Import validate_setup.py from its file path."""
    spec = importlib.util.spec_from_file_location("codex_validate_setup", VALIDATE_SETUP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_kalshi_requires_private_key_path(tmp_path):
    """CODEX: missing Kalshi key path should fail fast without touching the SDK."""
    module = load_validate_setup_module()

    result = module.validate_kalshi(
        {
            "kalshi": {
                "enabled": True,
                "api_key_id": "key-id",
            }
        }
    )

    assert result.passed is False
    assert result.error == "KALSHI_KEY_PATH not configured"


def test_validate_kalshi_rejects_missing_key_file(tmp_path):
    """CODEX: configured Kalshi key file must exist before any network call."""
    module = load_validate_setup_module()

    result = module.validate_kalshi(
        {
            "kalshi": {
                "enabled": True,
                "api_key_id": "key-id",
                "private_key_file": str(tmp_path / "missing.pem"),
            }
        }
    )

    assert result.passed is False
    assert "Private key file not found" in result.error


def test_validate_anthropic_reports_missing_key():
    """CODEX: Anthropic validator should fail clearly when no API key is configured."""
    module = load_validate_setup_module()

    result = module.validate_anthropic({})

    assert result.passed is False
    assert result.error == "ANTHROPIC_API_KEY not configured"


def test_validate_anthropic_success_with_fake_client(monkeypatch):
    """CODEX: Anthropic validator should mark success when the client returns content."""
    module = load_validate_setup_module()

    class FakeAnthropicClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.messages = self

        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(text="OK")])

    fake_module = SimpleNamespace(Anthropic=FakeAnthropicClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    result = module.validate_anthropic({"anthropic": {"api_key": "sk-test"}}, verbose=True)

    assert result.passed is True
    assert result.error is None


def test_validate_ollama_reports_missing_model(monkeypatch):
    """CODEX: Ollama validator should explain which model name is missing."""
    module = load_validate_setup_module()

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    fake_requests = SimpleNamespace(
        get=lambda *args, **kwargs: FakeResponse(200, {"models": [{"name": "llama3:latest"}]}),
        post=lambda *args, **kwargs: FakeResponse(200, {"response": "OK"}),
        exceptions=SimpleNamespace(ConnectionError=RuntimeError, Timeout=TimeoutError),
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    result = module.validate_ollama({"ollama": {"enabled": True, "model": "qwen3:latest"}})

    assert result.passed is False
    assert "Model 'qwen3:latest' not found" in result.error


def test_validate_ollama_success_with_fake_server(monkeypatch):
    """CODEX: Ollama validator should pass when tags and generate endpoints respond."""
    module = load_validate_setup_module()

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(*args, **kwargs):
        return FakeResponse(200, {"models": [{"name": "qwen3:latest"}]})

    def fake_post(*args, **kwargs):
        return FakeResponse(200, {"response": "OK", "eval_duration": 1_000_000_000})

    fake_requests = SimpleNamespace(
        get=fake_get,
        post=fake_post,
        exceptions=SimpleNamespace(ConnectionError=RuntimeError, Timeout=TimeoutError),
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    result = module.validate_ollama({"ollama": {"enabled": True, "model": "qwen3:latest"}}, verbose=True)

    assert result.passed is True
    assert result.error is None
