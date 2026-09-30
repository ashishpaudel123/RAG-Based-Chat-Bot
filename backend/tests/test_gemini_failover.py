"""GeminiProvider failover, exercised with a stubbed client (no network)."""

from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings
from app.services.llm import ChatTurn, GeminiProvider, LLMError


def make_provider(monkeypatch, responses, fallbacks="backup-model"):
    settings = Settings(GEMINI_API_KEY="test-key", llm_provider="gemini", gemini_model="main-model",
                        gemini_fallback_models=fallbacks, llm_max_retries=2)
    provider = GeminiProvider(settings)
    calls = []

    def generate_content(*, model, contents, config):
        calls.append(model)
        outcome = responses[model]
        if isinstance(outcome, int):
            raise errors.APIError(outcome, {"error": {"code": outcome, "message": "busy", "status": "UNAVAILABLE"}})
        return SimpleNamespace(text=outcome)

    monkeypatch.setattr(provider._client.models, "generate_content", generate_content)
    monkeypatch.setattr("app.services.llm.time.sleep", lambda _: None)
    return provider, calls


def test_falls_back_when_primary_overloaded(monkeypatch):
    provider, calls = make_provider(monkeypatch, {"main-model": 503, "backup-model": "answer"})
    assert provider.generate("sys", [ChatTurn("user", "hi")]) == "answer"
    assert calls == ["main-model", "main-model", "backup-model"]  # retried, then failed over
    assert provider.last_model == "backup-model"


def test_uses_primary_when_healthy(monkeypatch):
    provider, calls = make_provider(monkeypatch, {"main-model": "ok", "backup-model": "unused"})
    assert provider.generate("sys", [ChatTurn("user", "hi")]) == "ok"
    assert calls == ["main-model"] and provider.last_model == "main-model"


def test_raises_when_all_models_fail(monkeypatch):
    provider, _ = make_provider(monkeypatch, {"main-model": 503, "backup-model": 503})
    with pytest.raises(LLMError) as exc:
        provider.generate("sys", [ChatTurn("user", "hi")])
    assert exc.value.status_code == 503


def test_does_not_fail_over_on_client_errors(monkeypatch):
    provider, calls = make_provider(monkeypatch, {"main-model": 400, "backup-model": "unused"})
    with pytest.raises(LLMError):
        provider.generate("sys", [ChatTurn("user", "hi")])
    assert calls == ["main-model"]
