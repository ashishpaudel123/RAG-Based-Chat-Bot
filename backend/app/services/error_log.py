"""Operational error recording (FR-11).

Uses its own session so a failed business transaction does not lose the log
entry. Messages are truncated and must never include prompts or secrets.
"""

import logging

from app.database import SessionLocal
from app.models import ErrorLog

logger = logging.getLogger("chatbot")


def record_error(source: str, message: str, *, user_id: str | None = None, path: str | None = None,
                 level: str = "error") -> None:
    logger.log(logging.ERROR if level == "error" else logging.WARNING, "[%s] %s", source, message)
    try:
        with SessionLocal() as db:
            db.add(ErrorLog(level=level, source=source[:50], message=message[:2000], user_id=user_id,
                            path=(path or None) and path[:255]))
            db.commit()
    except Exception:  # logging must never break the request
        logger.exception("Failed to persist error log")
