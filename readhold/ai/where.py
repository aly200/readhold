"""Where text for the model goes (milestone 4.5): this computer, or somewhere else.

Kept apart from `adapters.py` on purpose: it holds no network code, so any module may ask it (the evaluation
harness, the guard), while only the adapters may open a connection (tests/test_no_network.py).
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_LOCAL = "http://localhost:11434"  # the endpoint when none is set (the settings default)


def is_local(url: str) -> bool:
    """Is this model server on this computer? Only `localhost` or a loopback address written as a number counts:
    a name that merely starts with "127." (127.evil.example) is somewhere else."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def destination(settings: dict) -> str:
    """Where text for the model in use goes, for the send preview: a cloud provider, or "remote:<host>"."""
    if settings.get("ai_mode") == "cloud":
        return str(settings.get("ai_cloud_provider") or "")
    try:
        return "remote:" + (urlsplit(str(settings.get("ai_local_endpoint") or DEFAULT_LOCAL)).hostname or "?")
    except ValueError:
        return "remote:?"


def leaves_computer(settings: dict) -> bool:
    """Does text sent to the model in use leave this computer? A cloud model, or a "local" server elsewhere (4.5)."""
    mode = settings.get("ai_mode")
    return mode == "cloud" or (mode == "local" and not is_local(str(settings.get("ai_local_endpoint") or DEFAULT_LOCAL)))
