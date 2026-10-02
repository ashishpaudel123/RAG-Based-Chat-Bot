"""Source metadata for knowledge documents (spec §5, §6, §16).

Metadata can come from a YAML front-matter block at the top of a Markdown/TXT
knowledge record and/or from the admin upload form (the form wins). Values
are validated here and mapped onto Document columns; unknown keys are kept in
``extra_metadata`` so nothing from the source inventory is lost.
"""

import datetime as dt
import re
from typing import Any

import yaml

from app.services.document_processing import FRONT_MATTER, DocumentValidationError

SOURCE_TYPES = {
    "constitution", "act", "amendment", "regulation", "directive", "circular", "official_notice", "form",
    "court_decision", "dao_charter", "local_notice", "official_portal", "secondary", "faq", "informal", "other",
}
# Default authority tier per source type (spec §5): 1 = primary law ... 5 = user-generated.
DEFAULT_TIER = {
    "constitution": 1, "act": 1, "amendment": 1, "regulation": 1, "directive": 1,
    "circular": 2, "official_notice": 2, "form": 2, "court_decision": 2, "official_portal": 2,
    "dao_charter": 3, "local_notice": 3,
    "secondary": 4, "faq": 4, "other": 3,
    "informal": 5,
}
VALIDITY = {"current", "superseded", "historical"}
VERIFICATION = {"verified", "pending", "rejected"}

# front-matter key aliases -> Document column
_ALIASES = {
    "id": "record_id", "record_id": "record_id", "rule_id": "record_id",
    "title": "title", "source_title": "title",
    "source_type": "source_type", "type": "source_type",
    "authority": "authority", "issuing_authority": "authority",
    "authority_tier": "authority_tier", "tier": "authority_tier",
    "category": "category",
    "legal_reference": "legal_reference", "section": "legal_reference",
    "jurisdiction": "jurisdiction",
    "district": "district",
    "status": "validity_status", "validity_status": "validity_status",
    "effective_from": "effective_from", "effective_date": "effective_from",
    "effective_until": "effective_until",
    "source_url": "source_url", "url": "source_url",
    "last_verified": "last_verified",
    "verification_status": "verification_status",
    "language": "language",
    "tags": "tags",
}

FIELDS = ("record_id", "source_type", "authority", "authority_tier", "category", "legal_reference", "jurisdiction",
          "district", "validity_status", "effective_from", "effective_until", "source_url", "last_verified",
          "verification_status", "language")


def split_front_matter(text: str) -> tuple[dict, str]:
    """Return (front-matter dict, body). Invalid YAML raises DocumentValidationError."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise DocumentValidationError(f"Invalid front matter: {exc}".splitlines()[0])
    if not isinstance(data, dict):
        raise DocumentValidationError("Front matter must be a key: value mapping")
    return data, text[match.end():]


def _plain(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if v not in (None, ""))
    value = " ".join(str(value).split())
    return value[:limit] or None


def normalize_metadata(raw: dict) -> tuple[dict, dict]:
    """Validate raw metadata. Returns (column values, extra metadata)."""
    columns: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        target = _ALIASES.get(str(key).strip().lower())
        if target is None:
            extra[str(key)] = _plain(value)
            continue
        if target in columns and key != target:
            extra[str(key)] = _plain(value)  # keep both e.g. title + source_title
            continue
        columns[target] = _plain(value)

    out: dict[str, Any] = {}
    if columns.get("title") is not None:
        out["title"] = _text(columns["title"], 255)
    if columns.get("tags") is not None:
        tags = columns["tags"]
        out["tags"] = [str(t) for t in (tags if isinstance(tags, list) else str(tags).split(","))]
    for name, limit in (("record_id", 120), ("authority", 255), ("category", 80), ("legal_reference", 255),
                        ("jurisdiction", 80), ("district", 80), ("effective_from", 40), ("effective_until", 40),
                        ("last_verified", 40), ("language", 40)):
        if name in columns:
            out[name] = _text(columns[name], limit)

    if columns.get("source_type") is not None:
        st = str(columns["source_type"]).strip().lower().replace(" ", "_")
        if st not in SOURCE_TYPES:
            raise DocumentValidationError(f"Unknown source_type '{st}'. Allowed: {', '.join(sorted(SOURCE_TYPES))}")
        out["source_type"] = st
    if columns.get("authority_tier") not in (None, ""):
        try:
            tier = int(columns["authority_tier"])
        except (TypeError, ValueError):
            raise DocumentValidationError("authority_tier must be a number from 1 to 5")
        if not 1 <= tier <= 5:
            raise DocumentValidationError("authority_tier must be a number from 1 to 5")
        out["authority_tier"] = tier
    if columns.get("validity_status") is not None:
        v = str(columns["validity_status"]).strip().lower()
        if v not in VALIDITY:
            raise DocumentValidationError(f"status must be one of: {', '.join(sorted(VALIDITY))}")
        out["validity_status"] = v
    if columns.get("verification_status") is not None:
        v = str(columns["verification_status"]).strip().lower()
        if v not in VERIFICATION:
            raise DocumentValidationError(f"verification_status must be one of: {', '.join(sorted(VERIFICATION))}")
        out["verification_status"] = v
    if columns.get("source_url"):
        url = str(columns["source_url"]).strip()
        if not re.match(r"^https?://[^\s]+$", url):
            raise DocumentValidationError("source_url must start with http:// or https://")
        out["source_url"] = url[:500]
    return out, extra


def apply_metadata(doc, values: dict, extra: dict | None = None) -> None:
    """Copy validated values onto a Document, filling the default tier from the source type."""
    for name, value in values.items():
        if name in ("tags", "title"):  # handled by the caller (form title wins)
            continue
        setattr(doc, name, value)
    if "source_type" in values and "authority_tier" not in values:
        doc.authority_tier = DEFAULT_TIER.get(doc.source_type, 3)
    if extra:
        doc.extra_metadata = {**(doc.extra_metadata or {}), **extra}
