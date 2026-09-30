"""Gemini Service: secure model API communication (§3.10).

The API key is read from server-side settings only. Transient failures
(rate limits, 5xx, timeouts) are retried with exponential backoff and then
surfaced as ``LLMError`` so callers can return a controlled message.
"""

import hashlib
import math
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Protocol

from app.config import Settings, get_settings

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class LLMError(Exception):
    """Raised when the model provider cannot produce a result."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


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
        max_output_tokens: int | None = None,
    ) -> str: ...

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]: ...


class GeminiProvider:
    name = "gemini"
    EMBED_BATCH = 100

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

    def _with_retries(self, fn):
        from google.genai import errors

        attempts = max(1, self.settings.llm_max_retries)
        for attempt in range(attempts):
            try:
                return fn()
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                retryable = code in (408, 429, 500, 502, 503, 504)
                if not retryable or attempt == attempts - 1:
                    detail = (getattr(exc, "message", None) or str(exc)).splitlines()[0][:300]
                    hint = ""
                    if code == 404:
                        hint = (" | Hint: the configured model is not available to this API key. Run "
                                "`python -m app.cli list-models` and set GEMINI_MODEL / GEMINI_EMBEDDING_MODEL in .env")
                    raise LLMError(f"Gemini API error ({code}): {detail}{hint}", retryable=retryable,
                                   status_code=code) from exc
            except Exception as exc:  # network errors, timeouts
                if attempt == attempts - 1:
                    raise LLMError(f"Gemini request failed: {type(exc).__name__}", retryable=True) from exc
            time.sleep(min(8, 2 ** attempt))
        raise LLMError("Gemini request failed")  # pragma: no cover

    def list_models(self) -> list:
        return list(self._with_retries(lambda: list(self._client.models.list())))

    def generate(self, system_instruction, turns, *, temperature=None, max_output_tokens=None) -> str:
        types = self._types
        contents = [types.Content(role=t.role, parts=[types.Part(text=t.text)]) for t in turns]
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self.settings.temperature if temperature is None else temperature,
            # Newer Gemini models spend output tokens on internal "thinking", so
            # small caps can produce empty answers; keep a generous floor.
            max_output_tokens=max(max_output_tokens or 0, self.settings.max_output_tokens),
        )
        response = self._with_retries(
            lambda: self._client.models.generate_content(model=self.model, contents=contents, config=config)
        )
        text = (response.text or "").strip() if response else ""
        if not text:
            raise LLMError("Gemini returned an empty response (possibly blocked by safety filters)")
        return text

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
                )
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

    def generate(self, system_instruction, turns, *, temperature=None, max_output_tokens=None) -> str:
        prompt = turns[-1].text if turns else ""
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
