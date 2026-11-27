"""Understanding terms without AI: definition finder and acronym expander."""
from __future__ import annotations

import re

STOP = {"of", "and", "the", "for", "in", "on", "to", "a", "an", "with", "by", "via", "from", "&"}


def find_acronyms(sentences: list[str]) -> dict[str, str]:
    """Detect "Long Form (LF)" and return {"LF": "Long Form"} using initial-letter matching."""
    found: dict[str, str] = {}
    pat = re.compile(r"\(([A-Z][A-Za-z0-9]{1,9}?)(s)?\)")
    for s in sentences:
        for m in pat.finditer(s):
            acr = m.group(1)
            letters = [c for c in acr if c.isupper() or c.isdigit()]
            if len(letters) < 2 or acr in found:
                continue
            before = re.findall(r"[A-Za-z0-9][\w-]*", s[: m.start()])[-(len(letters) + 4):]
            expansion = _match_initials(before, letters)
            if expansion:
                found[acr] = expansion
    return found


def _match_initials(words: list[str], letters: list[str]) -> str | None:
    """Shortest run of words before the parenthesis whose initials spell the acronym."""
    target = "".join(letters).lower()
    for start in range(len(words) - 1, -1, -1):
        cand = words[start:]
        if cand[0].lower() in STOP:
            continue
        initials = "".join(
            p[0] for w in cand if w.lower() not in STOP for p in w.split("-") if p
        ).lower()
        if initials == target:
            return " ".join(cand)
        if len(initials) > len(target) + 1:
            break
    return None


DEF_PATTERNS = [
    (r"(?<!\w){t}(?!\w),?\s+(?:is|are)\s+(?:defined as|called)\b", "defined as", 1.0),
    (r"\bwe\s+(?:define|call|term|denote|refer to)\b[^.]*(?<!\w){t}(?!\w)", "we define", 0.95),
    (r"(?<!\w){t}(?!\w)\s+(?:refers to|denotes|means|stands for|represents)\b", "refers to", 0.9),
    (r"\b(?:called|known as|termed|dubbed|named)\s+(?:the\s+|an?\s+)?[\"“']?{t}\b", "known as", 0.85),
    (r"(?<!\w){t}(?!\w)\s*(?:\([^)]*\))?,?\s+(?:is|are)\s+(?:a|an|the)\b", "X is a", 0.8),
    (r"(?<!\w){t}(?!\w)\s*:\s", "X:", 0.6),
    (r"(?<!\w){t}(?!\w)\s*\(", "X (…)", 0.4),
]


def find_definitions(term: str, sentences: list[tuple[int, str]], limit: int = 5) -> list[dict]:
    """Return candidate defining sentences ranked by pattern strength, earliest first on ties."""
    t = re.escape(term.strip())
    if not t:
        return []
    hits: list[dict] = []
    seen: set[int] = set()
    for pattern, label, weight in DEF_PATTERNS:
        rx = re.compile(pattern.format(t=t), re.IGNORECASE)
        for ord_, text in sentences:
            if ord_ in seen:
                continue
            if rx.search(text):
                hits.append({"sentence": ord_, "text": text, "pattern": label, "score": weight})
                seen.add(ord_)
    hits.sort(key=lambda h: (-h["score"], h["sentence"]))
    if not hits:  # fall back to the first use of the term
        rx = re.compile(rf"(?<!\w){t}(?!\w)", re.IGNORECASE)
        for ord_, text in sentences:
            if rx.search(text):
                hits.append({"sentence": ord_, "text": text, "pattern": "first use", "score": 0.1})
                break
    return hits[:limit]
