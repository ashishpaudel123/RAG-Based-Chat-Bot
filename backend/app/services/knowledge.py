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
from app.services.document_metadata import FIELDS, apply_metadata, normalize_metadata, split_front_matter
from app.services.error_log import record_error
from app.services.keyword_index import bump_knowledge_version
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


def doc_metadata(doc: Document) -> dict:
    """Document-level metadata stored on every vector (strings default to "")."""
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "version": doc.version,
        "tags": ",".join(doc.tags or []),
        "record_id": doc.record_id or "",
        "source_type": doc.source_type or "other",
        "authority": doc.authority or "",
        "authority_tier": int(doc.authority_tier or 3),
        "category": doc.category or "",
        "legal_reference": doc.legal_reference or "",
        "jurisdiction": doc.jurisdiction or "",
        "district": doc.district or "",
        "validity": doc.validity_status or "current",
        "verification": doc.verification_status or "verified",
        "effective_from": doc.effective_from or "",
        "effective_until": doc.effective_until or "",
        "source_url": doc.source_url or "",
        "last_verified": doc.last_verified or "",
        "language": doc.language or "",
    }


def chunk_metadata(doc: Document, chunk: Chunk) -> dict:
    return {**doc_metadata(doc), "chunk_index": chunk.chunk_index, "section": chunk.section or "",
            "page": chunk.page or 0}


def _front_matter(data: bytes, kind: str) -> tuple[dict, dict]:
    if kind not in ("md", "txt"):
        return {}, {}
    raw, _ = split_front_matter(data.decode("utf-8"))
    return normalize_metadata(raw)


def _store_file(filename: str, data: bytes) -> tuple[str, str]:
    name = safe_filename(filename)
    storage_name = f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    _storage_path(storage_name).write_bytes(data)
    return name, storage_name


def create_document(db: Session, *, filename: str, data: bytes, title: str | None, tags: list[str],
                    user_id: str, metadata: dict | None = None) -> Document:
    """Store and index a new document.

    ``metadata`` holds validated form values; they override the file's front
    matter. Uploading a file whose front-matter ``id`` matches a current
    document creates a new version of it instead (the old one is superseded).
    """
    settings = get_settings()
    kind = validate_upload(filename, data, settings.max_upload_bytes)
    digest = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Document).where(Document.sha256 == digest)):
        raise DocumentValidationError("An identical document is already in the knowledge base")
    fm_values, fm_extra = _front_matter(data, kind)
    values = {**fm_values, **{k: v for k, v in (metadata or {}).items() if v is not None}}
    if values.get("record_id"):
        previous = db.scalar(select(Document).where(Document.record_id == values["record_id"],
                                                    Document.validity_status == "current"))
        if previous is not None:
            return _new_version(db, previous, filename=filename, data=data, kind=kind, digest=digest,
                                values=values, extra=fm_extra, title=title, tags=tags, user_id=user_id)
    name, storage_name = _store_file(filename, data)
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        lineage_id=doc_id,
        title=(title or "").strip()[:255] or values.get("title") or title_from_filename(name),
        filename=name,
        storage_name=storage_name,
        content_type=kind,
        size_bytes=len(data),
        sha256=digest,
        tags=normalize_tags([*(values.get("tags") or []), *tags]),
        uploaded_by=user_id,
        source_type="other",
        authority_tier=3,
        validity_status="current",
        verification_status="verified",
    )
    apply_metadata(doc, values, fm_extra)
    db.add(doc)
    db.commit()
    index_document(db, doc)
    return doc


def _new_version(db: Session, old: Document, *, filename: str, data: bytes, kind: str, digest: str, values: dict,
                 extra: dict, title: str | None, tags: list[str] | None, user_id: str | None) -> Document:
    """Index a new version of ``old`` and, once it succeeds, mark ``old`` superseded.

    The old file, chunks and vectors are kept (spec §30) so historical
    questions can still be answered from them.
    """
    name, storage_name = _store_file(filename, data)
    new = Document(
        title=(title or "").strip()[:255] or values.get("title") or old.title,
        filename=name,
        storage_name=storage_name,
        content_type=kind,
        size_bytes=len(data),
        sha256=digest,
        version=old.version + 1,
        tags=normalize_tags([*(values.get("tags") or []), *(tags if tags is not None else old.tags or [])]),
        uploaded_by=user_id,
        lineage_id=old.lineage_id or old.id,
        supersedes_id=old.id,
        extra_metadata=dict(old.extra_metadata or {}),
    )
    for field in FIELDS:  # inherit source metadata unless the new file/form says otherwise
        setattr(new, field, getattr(old, field))
    new.authority_tier = old.authority_tier
    new.validity_status = "current"
    apply_metadata(new, values, extra)
    db.add(new)
    db.commit()
    index_document(db, new)
    if new.status == "indexed":
        old.validity_status = "superseded"
        if not old.effective_until:
            old.effective_until = new.effective_from or datetime.now(timezone.utc).date().isoformat()
        db.commit()
        sync_vector_metadata(old)
    return new


def replace_document(db: Session, doc: Document, *, filename: str | None, data: bytes | None,
                     title: str | None, tags: list[str] | None, metadata: dict | None = None,
                     clear: set[str] | None = None, user_id: str | None = None) -> Document:
    """Upload a new version (returns the new Document) or update metadata in place."""
    settings = get_settings()
    if data is not None and filename:
        kind = validate_upload(filename, data, settings.max_upload_bytes)
        digest = hashlib.sha256(data).hexdigest()
        if digest != doc.sha256:
            if db.scalar(select(Document).where(Document.sha256 == digest)):
                raise DocumentValidationError("An identical document is already in the knowledge base")
            fm_values, fm_extra = _front_matter(data, kind)
            values = {**fm_values, **{k: v for k, v in (metadata or {}).items() if v is not None}}
            return _new_version(db, doc, filename=filename, data=data, kind=kind, digest=digest, values=values,
                                extra=fm_extra, title=title, tags=tags, user_id=user_id)
    old_title = doc.title
    if title is not None and title.strip():
        doc.title = title.strip()[:255]
    if tags is not None:
        doc.tags = tags
    apply_metadata(doc, {k: v for k, v in (metadata or {}).items() if v is not None})
    for name in clear or ():
        if name in FIELDS and name not in ("source_type", "authority_tier", "validity_status", "verification_status"):
            setattr(doc, name, None)
    db.commit()
    if doc.title != old_title or doc.status != "indexed":
        index_document(db, doc)  # the title is part of each chunk's embedding input
    else:
        sync_vector_metadata(doc)  # metadata-only change: no embedding calls needed
    return doc


def sync_vector_metadata(doc: Document) -> None:
    get_vector_store().update_document_metadata(doc.id, doc_metadata(doc))
    bump_knowledge_version()


def sync_all_vector_metadata(db: Session) -> int:
    """Refresh vector metadata for every document (used after a schema upgrade)."""
    docs = list(db.scalars(select(Document)))
    for doc in docs:
        get_vector_store().update_document_metadata(doc.id, doc_metadata(doc))
    bump_knowledge_version()
    return len(docs)


def delete_document(db: Session, doc: Document) -> None:
    """Delete a document. Deleting the current version restores the version it superseded."""
    predecessor = db.get(Document, doc.supersedes_id) if doc.supersedes_id else None
    restore = predecessor is not None and doc.validity_status == "current" and predecessor.validity_status == "superseded"
    get_vector_store().delete_document(doc.id)
    _storage_path(doc.storage_name).unlink(missing_ok=True)
    db.delete(doc)
    if restore:
        predecessor.validity_status = "current"
        if predecessor.effective_until and predecessor.effective_until == doc.effective_from:
            predecessor.effective_until = None
    db.commit()
    if restore:
        sync_vector_metadata(predecessor)
    bump_knowledge_version()


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
        metadatas=[chunk_metadata(doc, c) for c in chunk_rows],
    )
    doc.status, doc.error, doc.chunk_count = "indexed", None, len(chunk_rows)
    doc.indexed_at = datetime.now(timezone.utc)
    db.commit()
    bump_knowledge_version()
    return len(chunk_rows)


def _mark_failed(db: Session, doc: Document, exc: Exception, *, drop_chunks: bool) -> None:
    db.rollback()
    if drop_chunks:
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        doc.chunk_count = 0
    doc.status, doc.error = "failed", str(exc)[:500]
    db.commit()
    bump_knowledge_version()
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
