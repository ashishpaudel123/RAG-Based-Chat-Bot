"""BM25 keyword index for hybrid retrieval (spec §14 stage 4).

Vector search alone misses exact legal terms, section numbers and noisy or
Romanized spellings; BM25 over normalized tokens complements it. The index is
built in memory from the chunk table and rebuilt lazily whenever the knowledge
base changes (``bump_knowledge_version``), which is fast at this project's
scale (thousands of chunks).
"""

import math
import threading
from collections import Counter
from dataclasses import dataclass

from app.services.normalization import tokenize


@dataclass
class KeywordHit:
    chunk_id: str
    text: str
    metadata: dict
    score: float
    coverage: float  # share of distinct query terms present in the chunk
    matched: int     # number of distinct query terms present


class BM25Index:
    def __init__(self, entries: list[tuple[str, str, dict]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self._ids, self._texts, self._metas = [], [], []
        self._tfs: list[Counter] = []
        self._lens: list[int] = []
        df: Counter = Counter()
        for chunk_id, text, meta in entries:
            # Title and section are part of what a chunk is "about".
            tokens = tokenize(f"{meta.get('document_title', '')} {meta.get('section', '')} {text}")
            tf = Counter(tokens)
            self._ids.append(chunk_id)
            self._texts.append(text)
            self._metas.append(meta)
            self._tfs.append(tf)
            self._lens.append(len(tokens))
            df.update(tf.keys())
        n = len(self._ids)
        self._avgdl = (sum(self._lens) / n) if n else 0.0
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, groups: list[set[str]], top_n: int, allow=None) -> list[KeywordHit]:
        """Score chunks for query term ``groups``.

        Each group is one user term plus its spelling/synonym variants (see
        ``Normalizer.groups``); a chunk matches a group if it has any variant.
        ``coverage`` is the share of groups matched. ``allow`` is an optional
        metadata predicate applied before scoring.
        """
        groups = [g & self._idf.keys() for g in groups]
        n_groups = len(groups)
        terms = set().union(*groups) if groups else set()
        if not terms:
            return []
        hits: list[KeywordHit] = []
        for i, tf in enumerate(self._tfs):
            if allow is not None and not allow(self._metas[i]):
                continue
            score = 0.0
            for t in terms:
                f = tf.get(t)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self._lens[i] / (self._avgdl or 1))
                    score += self._idf[t] * f * (self.k1 + 1) / denom
            if score <= 0:
                continue
            matched = sum(1 for g in groups if g and any(t in tf for t in g))
            hits.append(KeywordHit(self._ids[i], self._texts[i], self._metas[i], score, matched / n_groups, matched))
        hits.sort(key=lambda h: -h.score)
        return hits[:top_n]


# --------------------------------------------------------- app-level cache --
_version = 0
_cache: tuple[tuple, BM25Index] | None = None
_lock = threading.Lock()


def bump_knowledge_version() -> None:
    global _version
    with _lock:
        _version += 1


def _db_signature(db) -> tuple:
    """Cheap fingerprint of the knowledge base, so changes made by another process
    (e.g. ``python -m app.cli ingest`` while the server runs) are also picked up."""
    from sqlalchemy import func, select

    from app.models import Chunk, Document

    docs = db.execute(select(func.count(Document.id), func.max(Document.updated_at))).one()
    return (docs[0], str(docs[1]), db.scalar(select(func.count(Chunk.id))))


def get_app_keyword_index() -> BM25Index:
    """Index over all indexed chunks in the application database (cached)."""
    global _cache
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Chunk, Document
    from app.services.knowledge import chunk_metadata

    with SessionLocal() as db:
        signature = (_version, _db_signature(db))
        with _lock:
            if _cache is not None and _cache[0] == signature:
                return _cache[1]
        rows = db.execute(select(Chunk, Document).join(Document, Chunk.document_id == Document.id)).all()
        entries = [(c.id, c.text, chunk_metadata(d, c)) for c, d in rows]
    index = BM25Index(entries)
    with _lock:
        _cache = (signature, index)
    return index
