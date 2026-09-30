from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.deps import DB, AdminUser
from app.models import Chunk, Conversation, Document, ErrorLog, Feedback, Message, User
from app.schemas import ErrorLogOut, StatsOut, UserOut, UserUpdate

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, _: AdminUser):
    return db.scalars(select(User).order_by(User.created_at.desc())).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, db: DB, admin: AdminUser):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or disable your own account")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    return user


@router.get("/logs", response_model=list[ErrorLogOut])
def list_logs(db: DB, _: AdminUser, limit: int = 100):
    return db.scalars(select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(min(max(limit, 1), 500))).all()


@router.get("/stats", response_model=StatsOut)
def stats(db: DB, _: AdminUser):
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    assistant = Message.role == "assistant"
    answered = count(select(func.count(Message.id)).where(assistant))
    fallbacks = count(select(func.count(Message.id)).where(assistant, Message.is_fallback.is_(True)))
    avg_latency = db.scalar(select(func.avg(Message.latency_ms)).where(assistant, Message.latency_ms.is_not(None)))
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return StatsOut(
        users=count(select(func.count(User.id))),
        conversations=count(select(func.count(Conversation.id))),
        messages=count(select(func.count(Message.id))),
        documents=count(select(func.count(Document.id))),
        chunks=count(select(func.count(Chunk.id))),
        feedback_positive=count(select(func.count(Feedback.id)).where(Feedback.rating > 0)),
        feedback_negative=count(select(func.count(Feedback.id)).where(Feedback.rating < 0)),
        fallback_rate=round(fallbacks / answered, 4) if answered else 0.0,
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency is not None else None,
        errors_last_24h=count(select(func.count(ErrorLog.id)).where(ErrorLog.created_at >= since)),
    )
