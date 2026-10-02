"""Language and noise normalization for Nepali (Devanagari), Romanized Nepali,
English and mixed queries (spec §3, §14 stage 1, §22).

* ``tokenize`` produces keyword-search tokens for Devanagari and Latin text,
  folding Devanagari digits, common Nepali postpositions and noisy Roman
  spellings (repeated letters) so "nagarikataa" and "nagarikta" meet.
* ``Normalizer`` expands tokens through the profile's synonym dictionary so a
  Roman/English variant also matches its Devanagari canonical form.
* ``detect_language`` is a cheap heuristic used when no LLM analysis is
  available.
"""

import re
import unicodedata

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_TOKEN = re.compile(r"[0-9A-Za-zऀ-ॿ]+")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")

# Postpositions/suffixes that attach to Nepali nouns ("नागरिकताको" -> "नागरिकता").
_NE_SUFFIXES = ("हरूलाई", "हरूको", "हरू", "लाई", "बाट", "सँग", "देखि", "सम्म", "मा", "को", "का", "की", "ले", "द्वारा")

_STOP = {
    # English
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "for", "with", "what",
    "how", "do", "does", "did", "can", "i", "my", "me", "you", "your", "it", "this", "that", "at", "by", "from", "as",
    "if", "about", "which", "who", "when", "where", "why", "please", "should", "will", "would",
    # Romanized Nepali function words
    "ko", "ka", "ki", "ma", "lai", "le", "ra", "cha", "chha", "xa", "ho", "k", "ke", "ta", "pani", "ni", "mero",
    "meri", "malai", "hamro", "tapai", "tapaiko", "yo", "tyo", "garna", "garne", "huncha", "hunchha", "hunxa",
    # Devanagari function words
    "र", "छ", "हो", "के", "पनि", "यो", "त्यो", "मेरो", "मलाई", "तपाईं", "तपाईंको", "गर्न", "गर्ने", "हुन्छ", "कि", "न",
}

_ROMAN_NE_MARKERS = {
    "nagarikata", "nagrikata", "nagrita",
    "kasari", "kati", "garne", "garnu", "banaune", "banauna", "banaunu", "chaincha", "chahincha", "chahiyo",
    "milcha", "milchha", "milxa", "harayo", "vayo", "bhayo", "huncha", "hunxa", "xa", "cha", "chha", "ho", "ko",
    "ma", "lai", "bata", "mero", "malai", "aama", "babu", "baba", "nagarikta", "nagrikta", "barsa", "barsha",
    "kun", "kaha", "kahile", "parcha", "parchha", "sakincha", "paincha", "lagcha", "k", "ke", "ni",
}


def fold_digits(text: str) -> str:
    return text.translate(_DEV_DIGITS)


def _fold_latin(token: str) -> str:
    token = re.sub(r"([a-z])\1+", r"\1", token)  # nagarikataa -> nagarikata, chhaincha -> chaincha
    for suffix in ("ing", "ed", "es", "s"):    # light English stemming
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _fold_devanagari(token: str) -> str:
    for suffix in _NE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def normalize_token(token: str) -> str:
    token = fold_digits(token.lower())
    return _fold_devanagari(token) if _DEVANAGARI.search(token) else _fold_latin(token)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text or "")
    tokens = []
    for raw in _TOKEN.findall(text):
        if raw.lower() in _STOP:
            continue
        tok = normalize_token(raw)
        if tok and tok not in _STOP and (len(tok) > 1 or tok.isdigit()):
            tokens.append(tok)
    return tokens


def detect_language(text: str) -> str:
    """Return "ne", "en", "roman_ne" or "mixed"."""
    dev = len(_DEVANAGARI.findall(text))
    lat = len(_LATIN.findall(text))
    if dev and lat:
        return "ne" if dev > 3 * lat else "mixed"
    if dev:
        return "ne"
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    hits = len((words | {_fold_latin(w) for w in words}) & _ROMAN_NE_MARKERS)
    if hits >= 2 or (hits == 1 and len(words) <= 3):
        english = {"the", "is", "what", "how", "do", "i", "my", "can", "should", "documents", "required"}
        return "mixed" if len(words & english) >= 2 else "roman_ne"
    return "en"


class Normalizer:
    """Maps spelling/romanization variants to every term of their synonym group."""

    def __init__(self, synonyms: dict[str, list[str]]):
        self._groups: dict[str, set[str]] = {}
        for canonical, variants in (synonyms or {}).items():
            group: set[str] = set()
            for phrase in [canonical, *variants]:
                group.update(tokenize(phrase))
            for tok in group:
                self._groups.setdefault(tok, set()).update(group)

    def expand(self, tokens: list[str]) -> list[str]:
        out = list(tokens)
        seen = set(tokens)
        for tok in tokens:
            for extra in self._groups.get(tok, ()):
                if extra not in seen:
                    seen.add(extra)
                    out.append(extra)
        return out

    def groups(self, tokens: list[str]) -> list[set[str]]:
        """One set per distinct user token: the token plus its synonym variants."""
        return [{tok, *self._groups.get(tok, ())} for tok in dict.fromkeys(tokens)]
