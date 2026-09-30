from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.deps import DB
from app.schemas import HealthOut
from app.services.vector_store import get_vector_store

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(db: DB):
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    try:
        chunks = get_vector_store().count()
        vector = "ok"
    except Exception:
        chunks, vector = 0, "unavailable"
    llm_configured = settings.llm_provider == "fake" or bool(settings.gemini_api_key)
    return HealthOut(
        status="ok" if database == vector == "ok" and llm_configured else "degraded",
        database=database,
        vector_store=vector,
        llm_provider=settings.llm_provider,
        llm_configured=llm_configured,
        indexed_chunks=chunks,
        version=__version__,
    )
