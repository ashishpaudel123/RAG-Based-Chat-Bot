"""Administrative command line.

    python -m app.cli create-admin --email admin@example.com --name "Admin" --password Secret123
    python -m app.cli ingest ../sample_data --tags "policy"
    python -m app.cli reindex
    python -m app.cli list-models
"""

import argparse
import getpass
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import User
from app.security import hash_password
from app.services import knowledge
from app.services.document_processing import ALLOWED_TYPES, DocumentValidationError


def create_admin(args):
    password = args.password or getpass.getpass("Password: ")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user:
            user.role, user.is_active = "admin", True
            print(f"Promoted existing user {user.email} to admin")
        else:
            db.add(User(email=args.email.lower(), full_name=args.name, hashed_password=hash_password(password), role="admin"))
            print(f"Created admin {args.email.lower()}")
        db.commit()


def _admin_id(db) -> str:
    admin = db.scalar(select(User).where(User.role == "admin").order_by(User.created_at))
    if admin is None:
        raise SystemExit("Create an admin first (python -m app.cli create-admin ...)")
    return admin.id


def ingest(args):
    files = sorted(p for p in Path(args.path).rglob("*") if p.suffix.lower() in ALLOWED_TYPES
                   and not p.name.lower().startswith(("readme", "_")))
    if not files:
        raise SystemExit(f"No supported documents found in {args.path}")
    with SessionLocal() as db:
        admin_id = _admin_id(db)
        for path in files:
            try:
                doc = knowledge.create_document(db, filename=path.name, data=path.read_bytes(), title=None,
                                                tags=knowledge.normalize_tags(args.tags), user_id=admin_id)
                note = f"  v{doc.version}" if doc.version > 1 else ""
                note += "  [pending review - not searchable yet]" if doc.verification_status == "pending" else ""
                print(f"  {doc.status:8} {doc.chunk_count:3} chunks  {path.name}{note}"
                      + (f"  ({doc.error})" if doc.error else ""))
            except DocumentValidationError as exc:
                print(f"  skipped           {path.name}: {exc}")


def reindex(args):
    with SessionLocal() as db:
        run = knowledge.reindex(db, document_id=args.document_id, user_id=None)
        print(f"Indexed {run.documents_indexed} documents / {run.chunks_indexed} chunks "
              f"({run.failures} failures) in {run.duration_ms} ms")


def list_models(args):
    from app.config import get_settings
    from app.services.llm import GeminiProvider, LLMError

    settings = get_settings()
    try:
        models = GeminiProvider(settings).list_models()
    except LLMError as exc:
        raise SystemExit(f"Could not list models: {exc}")
    rows = []
    for m in models:
        actions = set(m.supported_actions or [])
        kind = "chat" if "generateContent" in actions else "embedding" if {"embedContent", "batchEmbedContents"} & actions else None
        if kind:
            rows.append((kind, (m.name or "").removeprefix("models/"), m.display_name or ""))
    for kind in ("chat", "embedding"):
        print(f"\n{kind.upper()} MODELS (use for {'GEMINI_MODEL' if kind == 'chat' else 'GEMINI_EMBEDDING_MODEL'}):")
        for _, name, display in sorted(r for r in rows if r[0] == kind):
            print(f"  {name:45} {display}")
    print(f"\nCurrently configured: GEMINI_MODEL={settings.gemini_model}  "
          f"GEMINI_EMBEDDING_MODEL={settings.gemini_embedding_model}")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Administrator")
    p.add_argument("--password")
    p.set_defaults(func=create_admin)
    p = sub.add_parser("ingest", help="upload and index every supported document in a folder")
    p.add_argument("path")
    p.add_argument("--tags", default="")
    p.set_defaults(func=ingest)
    p = sub.add_parser("list-models", help="show Gemini models available to the configured API key")
    p.set_defaults(func=list_models)
    p = sub.add_parser("reindex")
    p.add_argument("--document-id")
    p.set_defaults(func=reindex)
    args = parser.parse_args()
    init_db()
    args.func(args)


if __name__ == "__main__":
    main()
