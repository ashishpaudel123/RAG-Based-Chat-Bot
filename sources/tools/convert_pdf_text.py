"""Extract Unicode text from Nepali legal PDFs that use legacy fonts (Preeti, Himali, ...).

    pip install pymupdf npttf2utf
    python sources/tools/convert_pdf_text.py sources/pdfs/src-reg-2063.pdf sources/text/src-reg-2063.txt

* Converts only spans set in a legacy font, leaving real Unicode/Latin text untouched.
* Fixes rule/sub-rule numbers typed as ASCII digits in a Preeti span (e.g. "ज्ञ." -> "१.",
  "(द्द)" -> "(२)"). Clause letters that share codes with digits ("(घ)" = 3, "(छ)" = 5 ...) are
  decided from context: after "(ग)" it stays "(घ)", after "(२)" it becomes "(३)".
* Drops the repeated lines produced by faux-bold text.

Always check section/rule numbers against the PDF page images before relying on them.
"""

import glob
import os
import re
import sys

import npttf2utf
import pymupdf
from npttf2utf import FontMapper

LEGACY = ("preeti", "himal", "fontasy", "siddhi")
_MAPPER = FontMapper(glob.glob(os.path.join(os.path.dirname(npttf2utf.__file__), "**/*.json"), recursive=True)[0])
DEV_DIGITS = "०१२३४५६७८९"
LETTERS = "कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह"


def to_unicode(text: str) -> str:
    return _MAPPER.map_to_unicode(text, from_font="Preeti", unescape_html_input=False, escape_html_output=False)


DIGIT_GLYPHS = {to_unicode(str(i)): DEV_DIGITS[i] for i in range(10)}
_GLYPH_ALT = "|".join(sorted(map(re.escape, DIGIT_GLYPHS), key=len, reverse=True))
_MARKER = re.compile(rf"\(((?:{_GLYPH_ALT}|[{DEV_DIGITS}]|[{LETTERS}])+)\)")


def glyphs_to_digits(token: str) -> str | None:
    out = ""
    while token:
        for glyph in sorted(DIGIT_GLYPHS, key=len, reverse=True):
            if token.startswith(glyph):
                out += DIGIT_GLYPHS[glyph]
                token = token[len(glyph):]
                break
        else:
            if token[0] in DEV_DIGITS:
                out += token[0]
                token = token[1:]
            else:
                return None
    return out


def fix_numbers(text: str) -> str:
    # "ज्ञ." at the start of a line is a rule number (clauses always use parentheses).
    text = re.sub(rf"^(\s*)((?:{_GLYPH_ALT})+)(\s*\.)",
                  lambda m: m.group(1) + (glyphs_to_digits(m.group(2)) or m.group(2)) + m.group(3), text, flags=re.M)
    previous = None  # "digit" or "letter": kind of the previous (…) marker

    def marker(m):
        nonlocal previous
        token = m.group(1)
        if token.isdigit() or all(c in DEV_DIGITS for c in token):
            previous = "digit"
            return m.group(0)
        digits = glyphs_to_digits(token)
        if digits is None:
            previous = "letter"
            return m.group(0)
        is_letter_too = token in LETTERS  # घ, छ, ट, ठ, ड, ढ can be clause letters
        if is_letter_too and previous == "letter":
            return m.group(0)
        previous = "digit"
        return f"({digits})"

    return _MARKER.sub(marker, text)


def dedupe(text: str) -> str:
    lines, out = text.split("\n"), []
    for i, line in enumerate(lines):
        s = line.strip()
        if out and s and s == out[-1].strip():
            continue
        if s and i + 1 < len(lines) and lines[i + 1].strip().startswith(s) and len(lines[i + 1].strip()) > len(s):
            continue
        out.append(line)
    return "\n".join(out)


def convert(pdf_path: str, fix_digits: bool = True) -> str:
    pages = []
    for page in pymupdf.open(pdf_path):
        lines = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                lines.append("".join(to_unicode(s["text"]) if s["font"].lower().startswith(LEGACY) else s["text"]
                                     for s in line["spans"]))
        text = dedupe("\n".join(lines))
        pages.append(fix_numbers(text) if fix_digits else text)
    return "\n\n".join(f"===== page {i} =====\n{t}" for i, t in enumerate(pages, 1))


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    # Fonts like Himali already render Devanagari digits correctly; only Preeti PDFs need the digit fix.
    fix = "--no-digit-fix" not in sys.argv
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(convert(src, fix))
    print(f"wrote {dst}")
