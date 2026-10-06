"""Chat module: orchestrates one conversational turn (Figure 1.4).

validate -> load history -> build retrieval query -> search -> evidence check
-> grounded prompt -> Gemini -> persist message + citations -> respond.

Nothing is persisted if the model call fails, so the user can simply retry.
"""

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Citation, Conversation, Message, User
from app.services.keyword_index import get_app_keyword_index
from app.services.llm import get_llm
from app.services.memory import maybe_update_summary, recent_history
from app.services.rag import RAGPipeline
from app.services.vector_store import get_vector_store


def get_pipeline() -> RAGPipeline:
    return RAGPipeline(get_llm(), get_vector_store(), keyword_index=get_app_keyword_index)


def get_owned_conversation(db: Session, conversation_id: str, user: User) -> Conversation | None:
    """Ownership check (§3.11): users can only access their own conversations."""
    return db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))


def make_title(text: str) -> str:
    title = " ".join(text.split())
    return title if len(title) <= 60 else title[:57].rsplit(" ", 1)[0] + "…"


def handle_message(db: Session, user: User, conversation: Conversation | None, text: str) -> tuple[Conversation, Message, Message]:
    settings = get_settings()
    started = time.perf_counter()
    history_rows = list(conversation.messages) if conversation else []

    pipeline = get_pipeline()
    # Ask clarifying questions at most once in a row, so the user is never stuck in a loop.
    last_assistant = next((m for m in reversed(history_rows) if m.role == "assistant"), None)
    result = pipeline.answer(text, recent_history(history_rows), conversation.summary if conversation else None,
                             allow_clarification=not (last_assistant and (
                                 last_assistant.kind == "clarification"
                                 or (last_assistant.analysis or {}).get("follow_up"))))

    if conversation is None:
        conversation = Conversation(user_id=user.id, title=make_title(text))
        db.add(conversation)
        db.flush()
    elif conversation.title == "New conversation" and not history_rows:
        conversation.title = make_title(text)

    user_msg = Message(conversation_id=conversation.id, role="user", content=text)
    db.add(user_msg)
    db.flush()  # distinct created_at ordering for the assistant reply
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.answer,
        is_fallback=result.is_fallback,
        retrieval_query=result.retrieval_query,
        latency_ms=int((time.perf_counter() - started) * 1000),
        model=None if result.reason == "small_talk" else getattr(pipeline.llm, "last_model", pipeline.llm.model),
        prompt_version=settings.prompt_version,
        kind=result.kind,
        confidence=result.confidence,
        language=result.language,
        analysis={**result.analysis.to_dict(), "follow_up": bool(result.follow_up_questions)} if result.analysis else None,
        warnings=result.warnings or None,
    )
    # Guard against vectors whose chunk row was removed concurrently.
    live_chunks = set(db.scalars(select(Chunk.id).where(Chunk.id.in_([e.chunk_id for e in result.cited]))))
    assistant_msg.citations = [
        Citation(
            chunk_id=e.chunk_id if e.chunk_id in live_chunks else None,
            document_id=e.document_id,
            document_title=e.document_title,
            section=e.section,
            page=e.page,
            snippet=e.text[:700],
            score=e.score,
            rank=e.rank,
            source_type=e.source_type,
            authority_tier=e.authority_tier,
            validity_status=e.validity_status,
            legal_reference=e.legal_reference,
            district=e.district,
            effective_from=e.effective_from,
            source_url=e.source_url,
            last_verified=e.last_verified,
        )
        for e in result.cited
    ]
    db.add(assistant_msg)
    conversation.updated_at = datetime.now(timezone.utc)
    db.flush()

    maybe_update_summary(conversation, history_rows + [user_msg, assistant_msg], pipeline.llm)
    db.commit()
    db.refresh(conversation)
    return conversation, user_msg, assistant_msg
