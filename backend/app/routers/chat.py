from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models import Conversation, Message
from app.rate_limit import limit
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    ConversationSummary,
    MessageOut,
)
from app.services.chat import get_owned_conversation, handle_message
from app.services.error_log import record_error
from app.services.llm import LLMError

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def send_message(body: ChatRequest, request: Request, db: DB, user: CurrentUser):
    settings = get_settings()
    if len(body.message) > settings.max_message_chars:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Message is too long (maximum {settings.max_message_chars} characters)")
    limit("chat", user.id, settings.rate_limit_chat)

    conversation = None
    if body.conversation_id:
        conversation = get_owned_conversation(db, body.conversation_id, user)
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    try:
        conversation, user_msg, assistant_msg = handle_message(db, user, conversation, body.message)
    except LLMError as exc:
        db.rollback()
        record_error("gemini", str(exc), user_id=user.id, path=request.url.path)
        if exc.daily_quota:
            detail = "Today's AI usage limit has been reached. Please try again later or contact the administrator."
        elif exc.status_code == 429:
            detail = "The AI service is receiving too many requests. Please wait a minute and try again."
        else:
            detail = "The AI service is temporarily unavailable. Please try again shortly."
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    return ChatResponse(
        conversation_id=conversation.id,
        conversation_title=conversation.title,
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
    )


@router.get("/chats", response_model=list[ConversationSummary])
def list_chats(db: DB, user: CurrentUser):
    counts = (
        select(Message.conversation_id, func.count(Message.id).label("n"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(Conversation, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    ).all()
    return [
        ConversationSummary(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at, message_count=n)
        for c, n in rows
    ]


@router.post("/chats", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
def create_chat(body: ConversationCreate, db: DB, user: CurrentUser):
    conversation = Conversation(user_id=user.id, title=(body.title or "").strip() or "New conversation")
    db.add(conversation)
    db.commit()
    return ConversationSummary.model_validate(conversation)


@router.get("/chats/{conversation_id}", response_model=ConversationDetail)
def read_chat(conversation_id: str, db: DB, user: CurrentUser):
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .options(selectinload(Conversation.messages).selectinload(Message.citations),
                 selectinload(Conversation.messages).selectinload(Message.feedback))
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.patch("/chats/{conversation_id}", response_model=ConversationSummary)
def rename_chat(conversation_id: str, body: ConversationRename, db: DB, user: CurrentUser):
    conversation = get_owned_conversation(db, conversation_id, user)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    conversation.title = body.title.strip()
    db.commit()
    return ConversationSummary.model_validate(conversation)


@router.delete("/chats/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(conversation_id: str, db: DB, user: CurrentUser):
    conversation = get_owned_conversation(db, conversation_id, user)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    db.delete(conversation)
    db.commit()
