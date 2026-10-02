"""ChromaDB-backed vector knowledge base (initial vector storage, §4.2)."""

import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings


@dataclass
class VectorHit:
    chunk_id: str
    text: str
    metadata: dict
    score: float  # cosine similarity in [-1, 1]


class VectorStore:
    def __init__(self, path: str, collection: str):
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))
        self._name = collection
        self._lock = threading.Lock()
        self._collection = self._get_collection()

    def _get_collection(self):
        return self._client.get_or_create_collection(
            name=self._name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )

    def upsert(self, ids: list[str], embeddings: list[list[float]], texts: list[str], metadatas: list[dict]) -> None:
        if not ids:
            return
        clean = [{k: v for k, v in m.items() if v is not None} for m in metadatas]
        with self._lock:
            for i in range(0, len(ids), 500):
                self._collection.upsert(
                    ids=ids[i : i + 500],
                    embeddings=embeddings[i : i + 500],
                    documents=texts[i : i + 500],
                    metadatas=clean[i : i + 500],
                )

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self._collection.delete(where={"document_id": document_id})

    def reset(self) -> None:
        with self._lock:
            try:
                self._client.delete_collection(self._name)
            except Exception:
                pass
            self._collection = self._get_collection()

    def update_document_metadata(self, document_id: str, fields: dict) -> int:
        """Merge ``fields`` into the metadata of every chunk of a document (no re-embedding)."""
        clean = {k: v for k, v in fields.items() if v is not None}
        with self._lock:
            found = self._collection.get(where={"document_id": document_id}, include=["metadatas"])
            ids = found.get("ids") or []
            if ids:
                metas = [{**(m or {}), **clean} for m in found["metadatas"]]
                self._collection.update(ids=ids, metadatas=metas)
        return len(ids)

    def count(self) -> int:
        return self._collection.count()

    def query(self, embedding: list[float], top_k: int, where: dict | None = None) -> list[VectorHit]:
        if self.count() == 0:
            return []
        if where and len(where) > 1 and not any(k.startswith("$") for k in where):
            where = {"$and": [{k: v} for k, v in where.items()]}
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[VectorHit] = []
        for cid, text, meta, dist in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            hits.append(VectorHit(cid, text or "", dict(meta or {}), 1.0 - float(dist)))
        return hits


@lru_cache
def _store(path: str, collection: str) -> VectorStore:
    return VectorStore(path, collection)


def get_vector_store() -> VectorStore:
    s = get_settings()
    return _store(s.chroma_dir, s.chroma_collection)
