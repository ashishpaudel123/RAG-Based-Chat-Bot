"""GeminiProvider failover, exercised with a stubbed client (no network)."""

from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings
from app.services.llm import ChatTurn, GeminiProvider, LLMError


def quota_error(daily: bool, delay: str = "5s"):
    violation = {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if daily
                 else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}
    return errors.APIError(429, {"error": {"code": 429, "message": "You exceeded your current quota",
                                           "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [violation]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


def make_provider(monkeypatch, responses, fallbacks="backup-model"):
    settings = Settings(GEMINI_API_KEY="test-key", llm_provider="gemini", gemini_model="main-model",
                        gemini_fallback_models=fallbacks, llm_max_retries=2)
    provider = GeminiProvider(settings)
    calls = []

    def generate_content(*, model, contents, config):
        calls.append(model)
        outcome = responses[model]
        if isinstance(outcome, Exception):
            raise outcome
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


def test_daily_quota_fails_over_without_retrying(monkeypatch):
    provider, calls = make_provider(monkeypatch, {"main-model": quota_error(daily=True), "backup-model": "lite answer"})
    assert provider.generate("sys", [ChatTurn("user", "hi")]) == "lite answer"
    assert calls == ["main-model", "backup-model"]  # no wasted retry on the exhausted model


def test_daily_quota_error_is_flagged(monkeypatch):
    provider, _ = make_provider(monkeypatch, {"main-model": quota_error(daily=True)}, fallbacks="")
    with pytest.raises(LLMError) as exc:
        provider.generate("sys", [ChatTurn("user", "hi")])
    assert exc.value.status_code == 429 and exc.value.daily_quota


def test_document_embedding_waits_out_per_minute_limit(monkeypatch):
    provider, _ = make_provider(monkeypatch, {})
    sleeps, outcomes = [], [quota_error(daily=False, delay="3s"), None]

    def embed_content(*, model, contents, config):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0]) for _ in contents])

    monkeypatch.setattr(provider._client.models, "embed_content", embed_content)
    monkeypatch.setattr("app.services.llm.time.sleep", sleeps.append)
    assert provider.embed(["a", "b"], "RETRIEVAL_DOCUMENT") == [[1.0, 0.0], [1.0, 0.0]]
    assert sleeps == [4.0]


def test_query_embedding_fails_fast_on_rate_limit(monkeypatch):
    provider, _ = make_provider(monkeypatch, {})
    monkeypatch.setattr(provider._client.models, "embed_content",
                        lambda **_: (_ for _ in ()).throw(quota_error(daily=False)))
    with pytest.raises(LLMError) as exc:
        provider.embed(["q"], "RETRIEVAL_QUERY")
    assert exc.value.status_code == 429 and not exc.value.daily_quota
