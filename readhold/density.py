"""Density score: where the pacer slows down. Word rarity + length + numbers + symbols + acronyms.

Uses the wordfreq package's bundled frequency lists (stored locally, no network).
"""
from __future__ import annotations

import re
from functools import lru_cache

from wordfreq import zipf_frequency

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_NUM = re.compile(r"\d+(?:[.,]\d+)*%?")
_SYMBOL = re.compile(r"[=<>±×÷∑∏∫√∞≈≠≤≥∈∀∃∂∇^_{}|\\αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ]")
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,}s?\b")
RARE_ZIPF = 3.2  # below this a word is "rare" (≈ fewer than 1.6 per million words)


@lru_cache(maxsize=50_000)
def _zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def features(sentence: str) -> dict[str, float]:
    words = _WORD.findall(sentence)
    n = max(len(words), 1)
    content = [w for w in words if len(w) > 3]
    rare = sum(1 for w in content if _zipf(w.lower()) < RARE_ZIPF)
    return {
        "words": len(words),
        "rare_ratio": rare / max(len(content), 1) if content else 0.0,
        "length": min(n / 40.0, 1.0),
        "numbers": min(len(_NUM.findall(sentence)) / 4.0, 1.0),
        "symbols": min(len(_SYMBOL.findall(sentence)) / 4.0, 1.0),
        "acronyms": min(len(_ACRONYM.findall(sentence)) / 3.0, 1.0),
        "long_words": min(3 * sum(1 for w in words if len(w) >= 10) / n, 1.0),
    }


WEIGHTS = {"rare_ratio": 0.42, "length": 0.18, "numbers": 0.12, "symbols": 0.12, "acronyms": 0.08, "long_words": 0.08}


def score(sentence: str) -> float:
    """0 = easy, 1 = very dense. Rounded to 3 places for stable storage."""
    if not sentence.strip():
        return 0.0
    f = features(sentence)
    raw = sum(WEIGHTS[k] * f[k] for k in WEIGHTS)
    return round(max(0.0, min(1.0, raw * 1.6)), 3)
