from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth ----
class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Name is too short")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one letter and one number")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORM):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------- chat ----
class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class CitationOut(ORM):
    chunk_id: str | None
    document_id: str | None
    document_title: str
    section: str | None
    page: int | None
    snippet: str
    score: float
    rank: int
    source_type: str | None = None
    authority_tier: int | None = None
    validity_status: str | None = None
    legal_reference: str | None = None
    district: str | None = None
    effective_from: str | None = None
    source_url: str | None = None
    last_verified: str | None = None


class FeedbackOut(ORM):
    id: str
    rating: int
    comment: str | None
    created_at: datetime


class MessageOut(ORM):
    id: str
    role: str
    content: str
    is_fallback: bool
    latency_ms: int | None
    created_at: datetime
    kind: str | None = None
    confidence: str | None = None
    language: str | None = None
    citations: list[CitationOut] = []
    feedback: FeedbackOut | None = None


class ConversationSummary(ORM):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetail(ORM):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatResponse(BaseModel):
    conversation_id: str
    conversation_title: str
    user_message: MessageOut
    assistant_message: MessageOut


# ------------------------------------------------------------ feedback ----
class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)


# ----------------------------------------------------------- documents ----
class DocumentOut(ORM):
    id: str
    title: str
    filename: str
    content_type: str
    size_bytes: int
    version: int
    tags: list[str]
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None
    record_id: str | None = None
    source_type: str = "other"
    authority: str | None = None
    authority_tier: int = 3
    category: str | None = None
    legal_reference: str | None = None
    jurisdiction: str | None = None
    district: str | None = None
    validity_status: str = "current"
    effective_from: str | None = None
    effective_until: str | None = None
    source_url: str | None = None
    last_verified: str | None = None
    verification_status: str = "verified"
    language: str | None = None
    lineage_id: str | None = None
    supersedes_id: str | None = None


class ChunkOut(ORM):
    id: str
    chunk_index: int
    text: str
    section: str | None
    page: int | None


class ReindexRequest(BaseModel):
    document_id: str | None = None


class IndexRunOut(ORM):
    id: int
    scope: str
    embedding_model: str
    embedding_dimensions: int
    chunk_size: int
    chunk_overlap: int
    documents_indexed: int
    chunks_indexed: int
    failures: int
    duration_ms: int
    created_at: datetime


# --------------------------------------------------------------- admin ----
class UserUpdate(BaseModel):
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None


class ErrorLogOut(ORM):
    id: int
    level: str
    source: str
    message: str
    user_id: str | None
    path: str | None
    created_at: datetime


class StatsOut(BaseModel):
    users: int
    conversations: int
    messages: int
    documents: int
    chunks: int
    feedback_positive: int
    feedback_negative: int
    fallback_rate: float
    avg_latency_ms: float | None
    errors_last_24h: int


class HealthOut(BaseModel):
    status: str
    database: str
    vector_store: str
    llm_provider: str
    llm_configured: bool
    indexed_chunks: int
    version: str


class ProfileOut(BaseModel):
    id: str
    assistant_name: str
    tagline: str
    suggestions: list[str]
    answer_format: str
