"""Gemini Service: secure model API communication (§3.10).

The API key is read from server-side settings only. Transient failures
(rate limits, 5xx, timeouts) are retried with exponential backoff and then
surfaced as ``LLMError`` so callers can return a controlled message.
"""

import hashlib
import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Protocol

from app.config import Settings, get_settings

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class LLMError(Exception):
    """Raised when the model provider cannot produce a result."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None,
                 daily_quota: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.daily_quota = daily_quota  # a per-day quota was exhausted (will not recover soon)


@dataclass
class ChatTurn:
    role: Literal["user", "model"]
    text: str


class LLMProvider(Protocol):
    name: str
    model: str
    embedding_model: str

    def generate(
        self, system_instruction: str, turns: list[ChatTurn], *, temperature: float | None = None,
        max_output_tokens: int | None = None, json_mode: bool = False,
    ) -> str: ...

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]: ...


def _quota_details(exc) -> tuple[bool, float | None]:
    """Return (is_daily_quota, retry_delay_seconds) from a Gemini 429 error."""
    body = getattr(exc, "details", None) or {}
    items = body.get("error", {}).get("details", []) if isinstance(body, dict) else []
    daily, delay = False, None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        for violation in item.get("violations", []) or []:
            quota_id = f"{violation.get('quotaId', '')} {violation.get('quotaMetric', '')}"
            if "PerDay" in quota_id or "per_day" in quota_id.lower():
                daily = True
        retry = item.get("retryDelay")
        if isinstance(retry, str) and retry.endswith("s"):
            try:
                delay = float(retry[:-1])
            except ValueError:
                pass
    return daily, delay


def _api_error(exc, code, *, retryable: bool, daily_quota: bool = False) -> "LLMError":
    detail = (getattr(exc, "message", None) or str(exc)).splitlines()[0][:300]
    hint = ""
    if code == 404:
        hint = (" | Hint: the configured model is not available to this API key. Run "
                "`python -m app.cli list-models` and set GEMINI_MODEL / GEMINI_EMBEDDING_MODEL in .env")
    elif code == 429:
        hint = (" | Hint: daily quota for this model is used up; switch GEMINI_MODEL to a model with a higher "
                "free-tier limit (e.g. a Flash-Lite model) or enable billing" if daily_quota else
                " | Hint: per-minute rate limit reached; wait a minute or use a model with a higher limit")
    return LLMError(f"Gemini API error ({code}): {detail}{hint}", retryable=retryable, status_code=code,
                    daily_quota=daily_quota)


class GeminiProvider:
    name = "gemini"
    EMBED_BATCH = 50  # stays under the free-tier 100 embeddings/minute limit per batch

    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not configured on the server")
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000),
        )
        self.settings = settings
        self.model = settings.gemini_model
        self.embedding_model = settings.gemini_embedding_model
        # Primary model first, then fallbacks used when it is overloaded or unavailable.
        self.models = list(dict.fromkeys([settings.gemini_model, *settings.gemini_fallback_model_list]))
        self._local = threading.local()

    @property
    def last_model(self) -> str:
        """Model that served the most recent generate() call on this thread."""
        return getattr(self._local, "model", self.model)

    def _with_retries(self, fn, *, wait_for_rate_limit: bool = False):
        """Call ``fn`` with retries on transient errors.

        * 5xx / timeouts: retried with exponential backoff.
        * 429 quota errors: never blindly retried (that only burns more quota).
          Per-minute limits are waited out only when ``wait_for_rate_limit`` is
          set (background indexing); otherwise the error is raised at once so the
          caller can fail over to another model. Daily limits are never waited on.
        """
        from google.genai import errors

        attempts = max(1, self.settings.llm_max_retries)
        for attempt in range(attempts):
            try:
                return fn()
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code == 429:
                    daily, delay = _quota_details(exc)
                    if wait_for_rate_limit and not daily and attempt < attempts - 1:
                        time.sleep(min(65.0, (delay or 30.0) + 1.0))
                        continue
                    raise _api_error(exc, code, retryable=True, daily_quota=daily) from exc
                retryable = code in (408, 500, 502, 503, 504)
                if not retryable or attempt == attempts - 1:
                    raise _api_error(exc, code, retryable=retryable) from exc
            except Exception as exc:  # network errors, timeouts
                if attempt == attempts - 1:
                    raise LLMError(f"Gemini request failed: {type(exc).__name__}", retryable=True) from exc
            time.sleep(min(8, 2 ** attempt))
        raise LLMError("Gemini request failed")  # pragma: no cover

    def list_models(self) -> list:
        return list(self._with_retries(lambda: list(self._client.models.list())))

    def generate(self, system_instruction, turns, *, temperature=None, max_output_tokens=None,
                 json_mode=False) -> str:
        types = self._types
        contents = [types.Content(role=t.role, parts=[types.Part(text=t.text)]) for t in turns]
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self.settings.temperature if temperature is None else temperature,
            # Newer Gemini models spend output tokens on internal "thinking", so
            # small caps can produce empty answers; keep a generous floor.
            max_output_tokens=max(max_output_tokens or 0, self.settings.max_output_tokens),
            response_mime_type="application/json" if json_mode else None,
        )
        last_error: LLMError | None = None
        for model in self.models:
            try:
                response = self._with_retries(
                    lambda m=model: self._client.models.generate_content(model=m, contents=contents, config=config)
                )
            except LLMError as exc:
                # Fail over on overload/rate limit/outage or a model this key cannot use.
                if exc.retryable or exc.status_code == 404:
                    logging.getLogger("chatbot").warning("Model %s failed (%s); trying next model", model, exc)
                    last_error = exc
                    continue
                raise
            text = (response.text or "").strip() if response else ""
            if not text:
                raise LLMError("Gemini returned an empty response (possibly blocked by safety filters)")
            self._local.model = model
            return text
        raise last_error or LLMError("No Gemini model configured")

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]:
        types = self._types
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.EMBED_BATCH):
            batch = texts[i : i + self.EMBED_BATCH]
            config = types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=self.settings.embedding_dimensions
            )
            response = self._with_retries(
                lambda b=batch: self._client.models.embed_content(
                    model=self.embedding_model, contents=b, config=config
                ),
                # Indexing runs in the background of an admin action, so it can wait
                # out per-minute limits; interactive query embeddings fail fast.
                wait_for_rate_limit=task_type == "RETRIEVAL_DOCUMENT",
            )
            vectors.extend(_normalize(list(e.values)) for e in response.embeddings)
        return vectors


class FakeProvider:
    """Deterministic offline provider for tests and key-less demos.

    Embeddings are hashed bag-of-words vectors, so lexical overlap drives
    similarity. Generation extracts the most relevant evidence sentences.
    Not intended for real use.
    """

    name = "fake"
    DIM = 384

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = "fake-extractive"
        self.embedding_model = "fake-hash-embedding"

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.DIM] += 1.0
        return _normalize(vec)

    def generate(self, system_instruction, turns, *, temperature=None, max_output_tokens=None,
                 json_mode=False) -> str:
        prompt = turns[-1].text if turns else ""
        if "QUERY_ANALYSIS" in system_instruction:
            return self._fake_analysis(prompt)
        if "Rewrite the user's latest message" in system_instruction:
            match = re.search(r"Latest message:\s*(.+)", prompt, re.S)
            return (match.group(1) if match else prompt).strip()
        if "Summarise" in system_instruction:
            return "Earlier the user and assistant discussed: " + prompt[:300]
        if "<evidence>" not in prompt:
            return "I can only answer questions about the approved knowledge base."
        question = prompt.rsplit("Question:", 1)[-1].strip()
        q_tokens = set(_tokens(question))
        evidence = re.findall(r"<source id=\"(\d+)\"[^>]*>(.*?)</source>", prompt, re.S)
        scored: list[tuple[int, str, str]] = []
        for sid, body in evidence:
            for sentence in re.split(r"(?<=[.!?])\s+", body):
                overlap = len(q_tokens & set(_tokens(sentence)))
                if overlap:
                    scored.append((overlap, sid, sentence.strip()))
        if not scored:
            return "INSUFFICIENT_EVIDENCE"
        scored.sort(key=lambda x: -x[0])
        return " ".join(f"{s} [{sid}]" for _, sid, s in scored[:2])


    @staticmethod
    def _fake_analysis(prompt: str) -> str:
        """Heuristic stand-in for the LLM query analysis (no clarification, no intents)."""
        import json

        from app.services.normalization import detect_language

        match = re.search(r"<latest_message>\s*(.*?)\s*</latest_message>", prompt, re.S)
        question = (match.group(1) if match else prompt).strip()
        return json.dumps({
            "language": detect_language(question), "standalone_question": question, "search_queries": [question],
            "keywords": [], "intents": [], "facts": {}, "district": None, "time_reference": None,
            "source_preference": "both", "missing_facts": [], "needs_clarification": False,
            "clarifying_questions": [],
        })


_STOP = set("a an the is are was were be to of and or in on for with what how do does did can i my me you your "
            "it this that at by from as if about which who when where why".split())


def _stem(tok: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if tok.endswith(suffix) and len(tok) - len(suffix) >= 3:
            return tok[: -len(suffix)]
    return tok


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP and len(t) > 1]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache
def _cached_provider(provider: str, api_key: str | None, model: str) -> LLMProvider:
    settings = get_settings()
    if provider == "fake":
        return FakeProvider(settings)
    return GeminiProvider(settings)


def get_llm() -> LLMProvider:
    s = get_settings()
    return _cached_provider(s.llm_provider, s.gemini_api_key, s.gemini_model)
