"""The AI settings: their defaults and the check each value passes before it is stored.

They are ordinary settings rows (`DEFAULT_SETTINGS` in `readhold/server.py` includes `DEFAULTS`). An API key is
not a setting: it lives in the credential store (`keys.py`), and a value that looks like a key is refused here,
so a key pasted into the wrong box never reaches the database.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .. import redact
from . import keys

DEFAULTS: dict[str, Any] = {
    "ai_mode": "off",  # off | local | cloud. Off is the kill switch: nothing connects anywhere
    "ai_local_api": "ollama",  # ollama | openai (llama.cpp, LM Studio and others speak the OpenAI chat API)
    "ai_local_endpoint": "http://localhost:11434",
    "ai_local_model": "",
    "ai_local_small_model": "",  # for the short tasks; empty = the model above
    "ai_cloud_provider": "anthropic",  # anthropic | openai
    "ai_cloud_model": "",  # empty = the provider's default
    "ai_cloud_small_model": "",
    "ai_timeout_s": 60,
    "ai_budget_local": 2_000_000,  # tokens a day; 0 = no limit
    "ai_budget_cloud": 200_000,
    "ai_preview": False,  # cloud mode: show the exact text before it is sent, and send it only when you approve (4.4)
    "ai_log_days": 30,  # how long the AI log keeps its lines: 1, 7 or 30 days (4.4)
    "ai_cloud_only_tagged": False,  # cloud mode sends only documents and notes tagged #cloud (per-scope consent, 4.4)
}

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,119}")


def _endpoint(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError("The endpoint must be a web address.")
    value = value.strip()
    try:
        parts = urlsplit(value)
        host, _ = parts.hostname, parts.port  # reading the port checks it is a number
    except ValueError:
        raise ValueError("The endpoint must be a web address.") from None
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError("The endpoint must start with http:// or https:// and name a server.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("The endpoint must be a plain address: no user name, password or ?query in it.")
    return value


def _model(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("A model is named by text.")
    value = value.strip()
    if value and not _MODEL.fullmatch(value):
        raise ValueError("That is not a model name.")
    return value


def _number(low: float, high: float, whole: bool):
    def check(value: Any):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f"Expected a number between {low:g} and {high:g}.")
        return int(value) if whole else value

    return check


def _flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected on or off.")
    return value


def _days(value: Any) -> int:
    if isinstance(value, bool) or value not in (1, 7, 30):
        raise ValueError("The AI log is kept 1, 7 or 30 days.")
    return int(value)


def _one_of(*allowed: str):
    def check(value: Any) -> str:
        if value not in allowed:
            raise ValueError(f"Expected one of: {', '.join(allowed)}.")
        return value

    return check


CHECKS = {
    "ai_mode": _one_of("off", "local", "cloud"),
    "ai_local_api": _one_of("ollama", "openai"),
    "ai_local_endpoint": _endpoint,
    "ai_local_model": _model,
    "ai_local_small_model": _model,
    "ai_cloud_provider": _one_of(*keys.PROVIDERS),
    "ai_cloud_model": _model,
    "ai_cloud_small_model": _model,
    "ai_timeout_s": _number(5, 600, False),
    "ai_budget_local": _number(0, 1_000_000_000, True),
    "ai_budget_cloud": _number(0, 1_000_000_000, True),
    "ai_preview": _flag,
    "ai_log_days": _days,
    "ai_cloud_only_tagged": _flag,
}


def check(key: str, value: Any) -> Any:
    """The value as it will be stored. Raises ValueError with a sentence for the user."""
    if isinstance(value, str) and redact.looks_like_key(value):
        raise ValueError("That looks like an API key. Save it with the API key field instead; it is never stored in settings.")
    return CHECKS[key](value)
