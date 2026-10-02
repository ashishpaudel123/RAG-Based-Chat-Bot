"""Citation and claim validation (spec §13, §25, §40).

After generation, every citation marker must point to supplied evidence, and
every concrete figure the answer states - amounts of money, legal section/rule
numbers, and durations - must appear in the evidence text. Unsupported figures
are reported as warnings (and shown to the user) rather than silently trusted.
"""

import re
from dataclasses import dataclass, field

from app.services.normalization import fold_digits

_CITATION = re.compile(r"\[(\d+)\]")
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_CLAIM_PATTERNS = [
    # money: Rs 100, Rs. 1,000, NPR 500, रु. १००, १०० रुपैयाँ
    re.compile(rf"(?:rs\.?|npr|रु\.?|रू\.?)\s*{_NUM}", re.I),
    re.compile(rf"{_NUM}\s*(?:rupees?|रुपैयाँ|रुपियाँ)", re.I),
    # legal references: Section 3, दफा ३, नियम ७, Rule 7, Article 11, धारा ११, अनुसूची ४, Schedule 4
    re.compile(rf"(?:section|sec\.|rule|article|schedule|दफा|नियम|धारा|अनुसूची|उपदफा)\s*\(?{_NUM}", re.I),
    # durations: 7 days, ३५ दिन, 3 months, १६ वर्ष
    re.compile(rf"{_NUM}\s*(?:working\s+)?(?:days?|weeks?|months?|years?|दिन|हप्ता|महिना|वर्ष|बर्ष)", re.I),
]


@dataclass
class ValidationResult:
    answer: str
    cited_ranks: set[int]
    unsupported: list[str] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)


def _norm_number(value: str) -> str:
    return fold_digits(value).replace(",", "").rstrip(".")


def validate_answer(answer: str, evidence_texts: dict[int, str]) -> ValidationResult:
    """``evidence_texts`` maps citation rank -> evidence text."""
    valid = set(evidence_texts)
    invalid = sorted({int(n) for n in _CITATION.findall(answer)} - valid)
    if invalid:
        answer = _CITATION.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", answer)
    cited = {int(n) for n in _CITATION.findall(answer)}

    evidence_numbers = set()
    for text in evidence_texts.values():
        evidence_numbers.update(_norm_number(n) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", fold_digits(text)))

    unsupported: list[str] = []
    folded = fold_digits(answer)
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(folded):
            if _norm_number(match.group(1)) not in evidence_numbers:
                claim = " ".join(match.group(0).split())
                if claim not in unsupported:
                    unsupported.append(claim)
    return ValidationResult(answer=answer.strip(), cited_ranks=cited, unsupported=unsupported,
                            invalid_citations=invalid)
