"""Remove secrets from text before it is written anywhere: the log file and the AI log.

Two layers. Key-shaped strings (the patterns below) are removed wherever they appear. And every API key the app
has handled in this run is remembered in memory (never on disk), so that exact text is removed even from a line
that does not look like a key to the patterns.
"""
from __future__ import annotations

import logging
import re
import threading

MARK = "[redacted]"

_SHAPES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),  # OpenAI, Anthropic and many others
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/\-]{16,}=*"),
]
# a named secret: api_key=..., "password": "...", Authorization: ...   (the name stays, the value goes)
_NAMED = re.compile(
    r"(?i)\b((?:x-)?api[_-]?key|authorization|access[_-]?token|auth[_-]?token|secret|password|passwd)"
    r"(\"?\s*[:=]\s*\"?)(?!\[redacted\])([^\s\"',;&]{8,})"
)

_known: set[str] = set()
_lock = threading.Lock()


def remember(secret: str) -> None:
    """Keep a secret in memory so `clean` removes exactly it."""
    if secret and len(secret) >= 8:
        with _lock:
            _known.add(secret)


def forget_all() -> None:
    with _lock:
        _known.clear()


def strip_known(text: str) -> str:
    """Remove only the keys the app itself holds. For text that goes back to the reader, where a string that
    merely looks like a key (in a code file, say) must stay as it is."""
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for secret in known:
        if secret in text:
            text = text.replace(secret, MARK)
    return text


def clean(text: str) -> str:
    """Remove the keys the app holds and everything key-shaped. For anything that is written to disk as a log."""
    text = strip_known(text)
    for shape in _SHAPES:
        text = shape.sub(MARK, text)
    return _NAMED.sub(lambda m: m.group(1) + m.group(2) + MARK, text)


def scrub(text: str) -> tuple[str, int]:
    """`clean`, and how many secrets it removed."""
    before = text
    text = strip_known(text)
    n = max(0, text.count(MARK) - before.count(MARK))
    for shape in _SHAPES:
        text, k = shape.subn(MARK, text)
        n += k
    text, k = _NAMED.subn(lambda m: m.group(1) + m.group(2) + MARK, text)
    return text, n + k


_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# a phone number: "+" and digits, "(555) 123-4567", or 555-123-4567. Plain groups of digits ("10 000 000", a table row)
# are numbers, not phones, and stay.
_PHONE = re.compile(r"(?<![\w.])(?:\+\d[\d\s\-]{7,15}\d|\(\d{2,4}\)\s?\d{3,4}[\s\-]\d{3,4}|\d{3}-\d{3}-\d{4})(?![\w.\-])")


def scrub_all(text: str) -> tuple[str, int]:
    """For text that is about to leave this computer: keys, tokens, private keys and passwords (`scrub`), and also
    e-mail addresses and phone numbers. Returns the text and how many things were replaced."""
    text, n = scrub(text)
    for pattern in (_JWT, _EMAIL, _PHONE):
        text, k = pattern.subn(MARK, text)
        n += k
    return text, n


def looks_like_key(text: str) -> bool:
    return any(shape.search(text) for shape in _SHAPES) or bool(_NAMED.search(text))


class RedactingFormatter(logging.Formatter):
    """The formatter of data/logs/readhold.log: the finished line, traceback included, is cleaned before writing."""

    def format(self, record: logging.LogRecord) -> str:
        return clean(super().format(record))
