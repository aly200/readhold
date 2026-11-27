"""Rule-based text structure: sentence splitting, section kinds, cleanup. No AI."""
from __future__ import annotations

import re

ABBREVIATIONS = {
    "e.g", "i.e", "et al", "etc", "vs", "cf", "fig", "figs", "eq", "eqs", "sec", "secs", "tab", "ref", "refs",
    "dr", "mr", "mrs", "ms", "prof", "no", "nos", "vol", "pp", "approx", "resp", "al", "ch", "st", "jr", "sr",
    "inc", "ltd", "co", "dept", "univ", "min", "max", "avg", "est", "viz", "ca", "op", "ed", "eds",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

_SPLIT = re.compile(r"(?<=[.!?…])([\"'”’)\]]*)\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
# Math is stored as LaTeX between \( … \) (inline) and \[ … \] (display) — see importers.
MATH_SPAN = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.DOTALL)
_HOLD = re.compile("(\\d+)")


def _hold_math(text: str) -> tuple[str, list[str]]:
    """Swap formulas for placeholders so sentence rules never look inside LaTeX."""
    held: list[str] = []

    def stash(m: re.Match) -> str:
        held.append(m.group(0))
        return f"{len(held) - 1}"

    return MATH_SPAN.sub(stash, text), held


def _restore_math(text: str, held: list[str]) -> str:
    return _HOLD.sub(lambda m: held[int(m.group(1))], text) if held else text


def math_to_markdown(text: str) -> str:
    """\\( x \\) → $x$ and \\[ x \\] → $$x$$, the form Obsidian and most Markdown tools understand."""
    return MATH_SPAN.sub(lambda m: f"${m.group(1).strip()}$" if m.group(1) is not None else f"$${m.group(2).strip()}$$", text)


def plain_math(text: str) -> str:
    """Formulas keep their LaTeX but lose the delimiters (titles, tooltips)."""
    return MATH_SPAN.sub(lambda m: (m.group(1) or m.group(2) or "").strip(), text)


def normalize_ws(text: str) -> str:
    text = text.replace("­", "").replace(" ", " ")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # de-hyphenate line breaks
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\\\) ([,.;:!?)\]]|-(?=[A-Za-z]))", r"\\)\1", text)  # "\(d_k\) ," → "\(d_k\),", "\(d\) -dim" → "\(d\)-dim"
    text = re.sub(r"([(\[]) \\\(", r"\1\\(", text)  # "( \(x\)" → "(\(x\)"
    return text.strip()


def count_words(text: str) -> int:
    """Words to read; a formula counts as about one word per 6 characters of LaTeX (at least 1)."""
    held, maths = _hold_math(text)
    extra = sum(max(1, len(m) // 6) for m in maths)
    return len(_WORD.findall(_HOLD.sub(" ", held))) + extra


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, protecting abbreviations, initials, decimals, 'et al.' and formulas."""
    text, held = _hold_math(normalize_ws(text))
    return [_restore_math(p, held) for p in _split(text)]


def _split(text: str) -> list[str]:
    if not text:
        return []
    pieces: list[str] = []
    start = 0
    for m in _SPLIT.finditer(text):
        end = m.start() + len(m.group(1))
        candidate = text[start:end]
        last = re.search(r"([A-Za-z][A-Za-z.]*)\.$", candidate.rstrip("\"'”’)]"))
        if last:
            token = last.group(1).lower().rstrip(".")
            if token in ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
                continue  # "et al. Smith", "J. Smith", "Fig. 3"
        pieces.append(candidate.strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    # Merge fragments that are too short to stand alone (e.g. "1." list markers).
    merged: list[str] = []
    for p in pieces:
        if merged and (len(p) < 4 or re.fullmatch(r"[\d.()\[\]]+", p)):
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    return merged


SECTION_RULES: list[tuple[str, str]] = [
    (r"^abstract\b", "abstract"),
    (r"^(introduction|overview|motivation)\b", "intro"),
    (r"(related work|prior work|background|preliminaries|literature review)", "related"),
    (r"^(references|bibliography|works cited|citations)\b", "references"),
    (r"^(acknowledg)", "references"),
    (r"^(appendix|supplementary)", "appendix"),
    (r"(conclusion|concluding|summary|future work|limitations)", "conclusion"),
    (r"(discussion|analysis|ablation)", "discussion"),
    (r"(experiment|result|evaluation|benchmark|empirical|findings)", "results"),
    (r"(method|approach|model|architecture|framework|algorithm|design|implementation|setup|training|our )", "method"),
]

BACKGROUND_KINDS = {"related", "appendix"}
HIDDEN_KINDS = {"references"}


def section_kind(title: str) -> str:
    t = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVXivx]+\.|[A-Ha-h]\.)\s+", "", title.strip()).lower()
    for pattern, kind in SECTION_RULES:
        if re.search(pattern, t):
            return kind
    return "other"


def looks_like_heading(line: str) -> bool:
    """For plain text: short, no final period, numbered or Title Case / ALL CAPS."""
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";", ":")) and not re.match(r"^\d+(\.\d+)*\.$", s):
        return False
    words = s.split()
    if len(words) > 10:
        return False
    if re.match(r"^(\d+(\.\d+)*\.?|[IVX]+\.)\s+[A-Z]", s):
        return True
    if section_kind(s) != "other" and len(words) <= 4:
        return True
    if s.isupper() and len(words) <= 8 and any(c.isalpha() for c in s):
        return True
    caps = sum(1 for w in words if w[:1].isupper())
    return len(words) <= 6 and caps >= max(1, len(words) - 1) and not s.endswith("?")
