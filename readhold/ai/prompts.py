"""The prompt registry: prompts are plain files, one version per file (`prompts/<name>_v<N>.md`).

A prompt is the instruction for one feature and nothing else. It holds no document text and has no
placeholders: what a model reads from your library always goes into fenced sources (`guard.pack`), never
into the prompt. The highest version of a name is the one in use; its name goes into the AI log with every call.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path(__file__).with_name("prompts")
FILE = re.compile(r"([a-z][a-z0-9_]*?)_v(\d+)\.md")
NAME = re.compile(r"[a-z][a-z0-9_]{0,40}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str  # "resume_v1"
    text: str
    hash: str  # SHA-256 of the text


def versions(name: str) -> list[int]:
    out = []
    for f in FOLDER.glob("*.md"):
        m = FILE.fullmatch(f.name)
        if m and m.group(1) == name:
            out.append(int(m.group(2)))
    return sorted(out)


def load(name: str) -> Prompt:
    """The prompt in use for a feature. Raises KeyError for a name that has no file."""
    if not NAME.fullmatch(name or ""):
        raise KeyError(name)
    found = versions(name)
    if not found:
        raise KeyError(name)
    version = f"{name}_v{found[-1]}"
    text = (FOLDER / f"{version}.md").read_text("utf-8").strip()
    return Prompt(name, version, text, hashlib.sha256(text.encode("utf-8")).hexdigest())
