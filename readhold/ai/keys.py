"""API keys live in the operating system's credential store and nowhere else.

On Windows that is the Credential Manager, on macOS the Keychain, on Linux the Secret Service (GNOME Keyring or
KWallet), each reached through the `keyring` package. A key is never written to the
database, a settings row, a config file, a log or an API response; the app can say only whether one is set.
"""
from __future__ import annotations

import logging

import keyring
import keyring.errors

from .. import redact

log = logging.getLogger(__name__)
SERVICE = "Readhold"
OLD_SERVICE = "Foothold"  # the app's name until 2026-11-26: a key saved under it is moved on first use
PROVIDERS = ("anthropic", "openai")  # the cloud providers a key can be saved for


def _name(provider: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError("unknown provider")
    return f"ai-key:{provider}"


def tidy(key: str) -> str:
    """A pasted key without the spaces around it. Raises ValueError if it cannot be a key."""
    key = (key or "").strip()
    if not 12 <= len(key) <= 500 or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
        raise ValueError("That does not look like an API key.")
    return key


def get(provider: str) -> str | None:
    """The stored key, or None. A credential store that cannot be read counts as no key."""
    name = _name(provider)
    try:
        key = keyring.get_password(SERVICE, name)
        if not key and (key := keyring.get_password(OLD_SERVICE, name)):
            keyring.set_password(SERVICE, name, key)  # moved to the new name, then removed from the old one
            try:
                keyring.delete_password(OLD_SERVICE, name)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as e:  # noqa: BLE001  (no backend, a locked store, ...)
        log.warning("The credential store could not be read (%s).", type(e).__name__)
        return None
    if key:
        redact.remember(key)  # so it can never be written to the log, whatever line it ends up in
    return key or None


def is_set(provider: str) -> bool:
    return get(provider) is not None


def save(provider: str, key: str) -> None:
    name = _name(provider)
    key = tidy(key)
    redact.remember(key)
    keyring.set_password(SERVICE, name, key)


def clear(provider: str) -> None:
    try:
        keyring.delete_password(SERVICE, _name(provider))
    except keyring.errors.PasswordDeleteError:
        pass  # there was none
