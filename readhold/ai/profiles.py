"""Per-task model profiles (docs/ai/PLAN.md, section 7): which model, how varied, how long.

The defaults are `profiles.json` next to this file. What the user changed is kept in `data/ai_profiles.json`,
holding only the values that differ. A profile names a model size ("small" or "strong"); Settings say which
model each size is, for the local server and for the cloud provider.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)
DEFAULTS_FILE = Path(__file__).with_name("profiles.json")
# field -> (type, lowest, highest); "model" is checked on its own
LIMITS = {"temperature": (float, 0.0, 2.0), "top_p": (float, 0.0, 1.0), "min_p": (float, 0.0, 1.0), "max_output_tokens": (int, 16, 8192)}
SIZES = ("small", "strong")


def defaults() -> dict[str, dict]:
    return json.loads(DEFAULTS_FILE.read_text("utf-8"))


def _file() -> Path:
    return config.data_dir() / "ai_profiles.json"


def check(changes: object) -> dict[str, dict]:
    """The user's changes, checked. Raises ValueError with a sentence that says what is wrong."""
    base = defaults()
    if not isinstance(changes, dict):
        raise ValueError("Profiles must be an object of tasks.")
    out: dict[str, dict] = {}
    for task, fields in changes.items():
        if task not in base:
            raise ValueError(f"Unknown task: {str(task)[:40]}")
        if not isinstance(fields, dict):
            raise ValueError(f"{task}: expected an object.")
        kept = {}
        for name, value in fields.items():
            if name == "model":
                if value not in SIZES:
                    raise ValueError(f"{task}: model must be small or strong.")
            elif name in LIMITS:
                kind, low, high = LIMITS[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                    raise ValueError(f"{task}: {name} must be between {low} and {high}.")
                value = kind(value)
            else:
                raise ValueError(f"{task}: unknown setting {str(name)[:40]}")
            if base[task].get(name) != value:
                kept[name] = value
        if kept:
            out[task] = kept
    return out


def overrides() -> dict[str, dict]:
    f = _file()
    if not f.exists():
        return {}
    try:
        return check(json.loads(f.read_text("utf-8")))
    except (ValueError, OSError):
        log.warning("data/ai_profiles.json could not be read; using the default profiles.")
        return {}


def load() -> dict[str, dict]:
    """Every task's profile: the defaults with the user's changes on top."""
    out = defaults()
    for task, fields in overrides().items():
        out[task].update(fields)
    return out


def save(changes: object) -> dict[str, dict]:
    """Replace the user's changes (an empty object means: back to the defaults). Returns the profiles in use."""
    kept = check(changes)
    f = _file()
    if kept:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(kept, indent=1, sort_keys=True), "utf-8")
        os.replace(tmp, f)  # the file is whole or untouched, never half written
    else:
        f.unlink(missing_ok=True)
    return load()
