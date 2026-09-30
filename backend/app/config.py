"""Application configuration.

All secrets (Gemini API key, JWT secret, database password) are read from the
server-side environment only and are never sent to the frontend or placed in
model context (Proposal §3.11).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Customer Service Chatbot"
    environment: Literal["development", "test", "production"] = "development"

    # --- Persistence -------------------------------------------------------
    # PostgreSQL in Docker/production; SQLite is accepted for quick local runs.
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    chroma_dir: str = str(BASE_DIR / "data" / "chroma")
    chroma_collection: str = "knowledge_base"
    storage_dir: str = str(BASE_DIR / "data" / "documents")

    # --- Security ----------------------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:3000"
    admin_email: str | None = None
    admin_password: str | None = None
    admin_name: str = "Administrator"

    # Rate limits (requests per window per user) for expensive AI endpoints.
    rate_limit_chat: int = 20
    rate_limit_upload: int = 10
    rate_limit_auth: int = 10
    rate_limit_window_seconds: int = 60

    max_upload_mb: int = 10
    max_message_chars: int = 2000

    # --- Model provider ----------------------------------------------------
    # "gemini" is the production provider. "fake" is a deterministic offline
    # provider used by the automated tests and for demos without an API key.
    llm_provider: Literal["gemini", "fake"] = "gemini"
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    # Rolling aliases for Google's current Flash-Lite / Flash models. Flash-Lite
    # has far higher free-tier limits (e.g. 500 vs 20 requests/day), so it is the
    # default. Pin specific ids for reproducible evaluations (`python -m app.cli list-models`).
    gemini_model: str = "gemini-flash-lite-latest"
    # Comma-separated models tried in order when the primary model is overloaded
    # (503), out of quota (429) or unavailable. Empty string disables failover.
    gemini_fallback_models: str = "gemini-flash-latest"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    temperature: float = 0.2
    max_output_tokens: int = 4096
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    # --- RAG configuration (recorded with every index run, §4.6) ----------
    chunk_size: int = 1000          # characters
    chunk_overlap: int = 200        # characters
    top_k: int = 5
    relevance_threshold: float = 0.55  # minimum cosine similarity
    max_context_chunks: int = 4
    query_rewrite: bool = True      # rewrite follow-ups into standalone queries
    history_messages: int = 8       # recent messages sent as conversation memory
    summary_trigger_messages: int = 20  # summarise older history beyond this
    prompt_version: str = "v1.0"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gemini_fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
