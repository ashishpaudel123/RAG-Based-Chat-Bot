"""Domain profile: assistant identity, intents, fact fields, synonyms and
localized fixed messages. Lets the same RAG engine serve different knowledge
domains (e.g. Nepal citizenship, a store's customer service) by configuration.

Set DOMAIN_PROFILE to a built-in profile id (a file in app/profiles/) or to a
path of your own JSON file with the same keys.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"


@dataclass(frozen=True)
class DomainProfile:
    id: str
    assistant_name: str
    tagline: str
    domain_description: str
    role_description: str
    answer_format: str = "simple"  # "structured" (answer contract) or "simple"
    default_reply_language: str = "en"
    intents: tuple[str, ...] = ()
    fact_fields: tuple[str, ...] = ()
    clarification_guidance: str = ""
    suggestions: tuple[str, ...] = ()
    greetings: dict = field(default_factory=dict)
    thanks: dict = field(default_factory=dict)
    fallback_messages: dict = field(default_factory=dict)
    verification_note: dict = field(default_factory=dict)
    synonyms: dict = field(default_factory=dict)

    def text(self, key: str, language: str) -> str:
        """Localized fixed message; Nepali for ne/roman_ne/mixed, else English."""
        messages: dict = getattr(self, key)
        lang = "ne" if language in ("ne", "roman_ne", "mixed") else "en"
        return messages.get(lang) or messages.get(self.default_reply_language) or next(iter(messages.values()), "")


def load_profile(name_or_path: str) -> DomainProfile:
    path = Path(name_or_path)
    if not path.suffix:
        path = PROFILE_DIR / f"{name_or_path}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("intents", "fact_fields", "suggestions"):
        data[key] = tuple(data.get(key, ()))
    known = DomainProfile.__dataclass_fields__
    return DomainProfile(**{k: v for k, v in data.items() if k in known})


@lru_cache
def _cached(name: str) -> DomainProfile:
    return load_profile(name)


def get_profile() -> DomainProfile:
    return _cached(get_settings().domain_profile)
