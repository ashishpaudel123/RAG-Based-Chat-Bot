import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import __version__
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import User
from app.routers import admin, auth, chat, documents, feedback, health
from app.security import hash_password
from app.services.error_log import record_error
from app.services.profile import get_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("chatbot")
settings = get_settings()


def seed_admin() -> None:
    """Create the bootstrap administrator from ADMIN_EMAIL / ADMIN_PASSWORD if absent."""
    if not settings.admin_email or not settings.admin_password:
        return
    with SessionLocal() as db:
        email = settings.admin_email.lower()
        if db.scalar(select(User).where(User.email == email)):
            return
        db.add(User(email=email, full_name=settings.admin_name, hashed_password=hash_password(settings.admin_password),
                    role="admin"))
        db.commit()
        logger.info("Created bootstrap admin account %s", email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment == "production" and settings.jwt_secret == "change-me-in-production":
        raise RuntimeError("JWT_SECRET must be set in production")
    added = init_db()
    if added:
        logger.info("Database upgraded: added columns %s", ", ".join(added))
    if any(col.startswith("documents.") for col in added):
        # New source-metadata columns: copy their defaults onto existing vectors so
        # filtering works without re-embedding anything.
        from app.services.knowledge import sync_all_vector_metadata

        with SessionLocal() as db:
            logger.info("Refreshed vector metadata for %d documents", sync_all_vector_metadata(db))
    get_profile()  # fail fast on a missing/invalid DOMAIN_PROFILE
    seed_admin()
    if settings.llm_provider == "gemini" and not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set: chat and indexing will fail until it is configured")
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Retrieval-Augmented customer service chatbot powered by Gemini.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    record_error("server", f"{type(exc).__name__}: {exc}", path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. Please try again."})


for r in (auth.router, chat.router, documents.router, feedback.router, admin.router, health.router):
    app.include_router(r)
