from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import DB, CurrentUser
from app.models import Conversation, Feedback, Message
from app.schemas import FeedbackOut, FeedbackRequest

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/feedback", response_model=FeedbackOut)
def submit_feedback(body: FeedbackRequest, db: DB, user: CurrentUser):
    message = db.scalar(
        select(Message)
        .join(Conversation)
        .where(Message.id == body.message_id, Conversation.user_id == user.id)
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if message.role != "assistant":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Feedback can only be given on assistant responses")
    comment = (body.comment or "").strip() or None
    feedback = message.feedback
    if feedback is None:
        feedback = Feedback(message_id=message.id, user_id=user.id, rating=body.rating, comment=comment)
        db.add(feedback)
    else:  # one rating per response; later submissions update it
        feedback.rating, feedback.comment = body.rating, comment
    db.commit()
    return feedback
