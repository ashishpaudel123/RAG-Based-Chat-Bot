from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, AdminUser
from app.models import Chunk, Document, IndexRun
from app.rate_limit import limit
from app.schemas import ChunkOut, DocumentOut, IndexRunOut, ReindexRequest
from app.services import knowledge
from app.services.document_metadata import normalize_metadata
from app.services.document_processing import DocumentValidationError

router = APIRouter(prefix="/api", tags=["knowledge"])


def metadata_form(
    source_type: Annotated[str | None, Form(max_length=30)] = None,
    authority: Annotated[str | None, Form(max_length=255)] = None,
    authority_tier: Annotated[str | None, Form(max_length=2)] = None,
    category: Annotated[str | None, Form(max_length=80)] = None,
    legal_reference: Annotated[str | None, Form(max_length=255)] = None,
    jurisdiction: Annotated[str | None, Form(max_length=80)] = None,
    district: Annotated[str | None, Form(max_length=80)] = None,
    validity_status: Annotated[str | None, Form(max_length=20)] = None,
    effective_from: Annotated[str | None, Form(max_length=40)] = None,
    effective_until: Annotated[str | None, Form(max_length=40)] = None,
    source_url: Annotated[str | None, Form(max_length=500)] = None,
    last_verified: Annotated[str | None, Form(max_length=40)] = None,
    verification_status: Annotated[str | None, Form(max_length=20)] = None,
    language: Annotated[str | None, Form(max_length=40)] = None,
) -> dict:
    """Optional source-metadata form fields. Omitted fields are left unchanged; an empty
    string clears a free-text field."""
    raw = {k: v for k, v in locals().items() if v is not None}
    clear = {k for k, v in raw.items() if v.strip() == ""}
    try:
        values, _ = normalize_metadata({k: v for k, v in raw.items() if k not in clear})
    except DocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    for k in clear:
        if k not in ("source_type", "authority_tier", "validity_status", "verification_status"):
            values[k] = None
    return {"values": values, "clear": clear}


MetadataForm = Annotated[dict, Depends(metadata_form)]


async def _read_limited(file: UploadFile) -> bytes:
    max_bytes = get_settings().max_upload_bytes
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds the {get_settings().max_upload_mb} MB limit")
    return data


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: DB, _: AdminUser):
    return db.scalars(select(Document).order_by(Document.created_at.desc())).all()


@router.post("/documents/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    db: DB,
    admin: AdminUser,
    file: Annotated[UploadFile, File()],
    meta: MetadataForm,
    title: Annotated[str | None, Form(max_length=255)] = None,
    tags: Annotated[str | None, Form(max_length=500)] = None,
):
    limit("upload", admin.id, get_settings().rate_limit_upload)
    data = await _read_limited(file)
    try:
        return knowledge.create_document(
            db, filename=file.filename or "", data=data, title=title, tags=knowledge.normalize_tags(tags),
            user_id=admin.id, metadata=meta["values"],
        )
    except DocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: DB, _: AdminUser):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
def get_document_chunks(document_id: str, db: DB, _: AdminUser):
    if db.get(Document, document_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return db.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)).all()


@router.put("/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: str,
    db: DB,
    admin: AdminUser,
    meta: MetadataForm,
    file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str | None, Form(max_length=255)] = None,
    tags: Annotated[str | None, Form(max_length=500)] = None,
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    limit("upload", admin.id, get_settings().rate_limit_upload)
    data = await _read_limited(file) if file is not None and file.filename else None
    try:
        return knowledge.replace_document(
            db, doc, filename=file.filename if data is not None else None, data=data, title=title,
            tags=knowledge.normalize_tags(tags) if tags is not None else None,
            metadata=meta["values"], clear=meta["clear"], user_id=admin.id,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: DB, _: AdminUser):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    knowledge.delete_document(db, doc)


@router.post("/knowledge/reindex", response_model=IndexRunOut)
def reindex_knowledge(db: DB, admin: AdminUser, body: ReindexRequest | None = None):
    limit("upload", admin.id, get_settings().rate_limit_upload)
    try:
        return knowledge.reindex(db, document_id=body.document_id if body else None, user_id=admin.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.get("/knowledge/runs", response_model=list[IndexRunOut])
def index_runs(db: DB, _: AdminUser):
    return db.scalars(select(IndexRun).order_by(IndexRun.created_at.desc()).limit(20)).all()
