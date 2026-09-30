"""Knowledge Management module: document storage, indexing and re-indexing."""

import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document, IndexRun
from app.services.document_processing import (
    DocumentValidationError,
    TextChunk,
    chunk_blocks,
    parse_document,
    safe_filename,
    title_from_filename,
    validate_upload,
)
from app.services.error_log import record_error
from app.services.llm import LLMError, get_llm
from app.services.vector_store import get_vector_store


def _storage_path(storage_name: str) -> Path:
    root = Path(get_settings().storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / storage_name


def normalize_tags(raw: str | list[str] | None) -> list[str]:
    if not raw:
        return []
    items = raw.split(",") if isinstance(raw, str) else raw
    tags = []
    for t in items:
        t = " ".join(str(t).split()).lower()[:40]
        if t and t not in tags:
            tags.append(t)
    return tags[:10]


def create_document(db: Session, *, filename: str, data: bytes, title: str | None, tags: list[str],
                    user_id: str) -> Document:
    settings = get_settings()
    kind = validate_upload(filename, data, settings.max_upload_bytes)
    digest = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Document).where(Document.sha256 == digest)):
        raise DocumentValidationError("An identical document is already in the knowledge base")
    name = safe_filename(filename)
    storage_name = f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    _storage_path(storage_name).write_bytes(data)
    doc = Document(
        title=(title or "").strip()[:255] or title_from_filename(name),
        filename=name,
        storage_name=storage_name,
        content_type=kind,
        size_bytes=len(data),
        sha256=digest,
        tags=tags,
        uploaded_by=user_id,
    )
    db.add(doc)
    db.commit()
    index_document(db, doc)
    return doc


def replace_document(db: Session, doc: Document, *, filename: str | None, data: bytes | None,
                     title: str | None, tags: list[str] | None) -> Document:
    """Update metadata and/or upload a new version of an existing document."""
    settings = get_settings()
    if data is not None and filename:
        kind = validate_upload(filename, data, settings.max_upload_bytes)
        digest = hashlib.sha256(data).hexdigest()
        if digest != doc.sha256:
            clash = db.scalar(select(Document).where(Document.sha256 == digest, Document.id != doc.id))
            if clash:
                raise DocumentValidationError("An identical document is already in the knowledge base")
            old_path = _storage_path(doc.storage_name)
            name = safe_filename(filename)
            doc.storage_name = f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
            _storage_path(doc.storage_name).write_bytes(data)
            old_path.unlink(missing_ok=True)
            doc.filename, doc.content_type, doc.size_bytes, doc.sha256 = name, kind, len(data), digest
            doc.version += 1
    if title is not None and title.strip():
        doc.title = title.strip()[:255]
    if tags is not None:
        doc.tags = tags
    db.commit()
    # Title/tags/version are part of chunk metadata, so any change re-indexes.
    index_document(db, doc)
    return doc


def delete_document(db: Session, doc: Document) -> None:
    get_vector_store().delete_document(doc.id)
    _storage_path(doc.storage_name).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


def _prepare(doc: Document) -> tuple[list[TextChunk], list[list[float]]]:
    """Parse, chunk and embed a document without touching any stored state."""
    settings = get_settings()
    data = _storage_path(doc.storage_name).read_bytes()
    blocks = parse_document(data, doc.content_type)
    pieces = chunk_blocks(blocks, settings.chunk_size, settings.chunk_overlap)
    # Prefix the title/section so the embedding captures document context.
    embed_inputs = [f"{doc.title}\n{p.section or ''}\n{p.text}".strip() for p in pieces]
    return pieces, get_llm().embed(embed_inputs, "RETRIEVAL_DOCUMENT")


def _apply(db: Session, doc: Document, pieces: list[TextChunk], vectors: list[list[float]]) -> int:
    """Replace a document's chunks and vectors with freshly prepared ones."""
    store = get_vector_store()
    store.delete_document(doc.id)
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    chunk_rows = [
        Chunk(document_id=doc.id, chunk_index=p.index, text=p.text, section=p.section, page=p.page,
              char_count=len(p.text))
        for p in pieces
    ]
    db.add_all(chunk_rows)
    db.flush()
    store.upsert(
        ids=[c.id for c in chunk_rows],
        embeddings=vectors,
        texts=[c.text for c in chunk_rows],
        metadatas=[
            {
                "document_id": doc.id,
                "document_title": doc.title,
                "chunk_index": c.chunk_index,
                "section": c.section,
                "page": c.page,
                "version": doc.version,
                "tags": ",".join(doc.tags or []),
            }
            for c in chunk_rows
        ],
    )
    doc.status, doc.error, doc.chunk_count = "indexed", None, len(chunk_rows)
    doc.indexed_at = datetime.now(timezone.utc)
    db.commit()
    return len(chunk_rows)


def _mark_failed(db: Session, doc: Document, exc: Exception, *, drop_chunks: bool) -> None:
    db.rollback()
    if drop_chunks:
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        doc.chunk_count = 0
    doc.status, doc.error = "failed", str(exc)[:500]
    db.commit()
    record_error("indexing", f"Document {doc.id}: {exc}")


def index_document(db: Session, doc: Document) -> int:
    """Parse, chunk, embed and index one document. Returns the chunk count.

    Embedding happens before anything is replaced, so on failure the
    previously indexed chunks stay searchable; the admin sees the error and
    can retry.
    """
    try:
        pieces, vectors = _prepare(doc)
        return _apply(db, doc, pieces, vectors)
    except (DocumentValidationError, LLMError, OSError) as exc:
        _mark_failed(db, doc, exc, drop_chunks=False)
        return 0


def reindex(db: Session, *, document_id: str | None, user_id: str | None) -> IndexRun:
    settings = get_settings()
    llm = get_llm()
    started = time.perf_counter()
    total_chunks = failures = 0
    if document_id:
        doc = db.get(Document, document_id)
        if doc is None:
            raise LookupError("Document not found")
        docs = [doc]
        total_chunks = index_document(db, doc)
        failures = int(doc.status == "failed")
    else:
        # Full rebuild: embed everything first, then reset the collection so
        # embedding model/dimension changes take effect. If the embedding
        # service fails part-way, the existing index is left untouched.
        docs = list(db.scalars(select(Document).order_by(Document.created_at)))
        prepared: dict[str, tuple[list[TextChunk], list[list[float]]]] = {}
        errors: dict[str, Exception] = {}
        for doc in docs:
            try:
                prepared[doc.id] = _prepare(doc)
            except (DocumentValidationError, LLMError, OSError) as exc:
                errors[doc.id] = exc
        if any(isinstance(e, LLMError) for e in errors.values()):
            for doc in docs:
                if doc.id in errors:
                    _mark_failed(db, doc, errors[doc.id], drop_chunks=False)
            failures = len(errors)
            record_error("indexing", "Full re-index aborted: embedding service failed; existing index kept")
            docs = []  # nothing was re-indexed
        else:
            get_vector_store().reset()
            for doc in docs:
                if doc.id in prepared:
                    total_chunks += _apply(db, doc, *prepared[doc.id])
                else:  # unreadable document: its old vectors are gone after the reset
                    _mark_failed(db, doc, errors[doc.id], drop_chunks=True)
                    failures += 1
    run = IndexRun(
        scope=document_id or "full",
        triggered_by=user_id,
        embedding_model=llm.embedding_model,
        embedding_dimensions=settings.embedding_dimensions if llm.name == "gemini" else 384,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        documents_indexed=max(0, len(docs) - failures),
        chunks_indexed=total_chunks,
        failures=failures,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(run)
    db.commit()
    return run
