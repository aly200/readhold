"""The one internal shape every import ends in: sections of paragraphs (split into sentences on save)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PPara:
    text: str
    kind: str = "text"  # text | code | caption | equation | reference | list | fragment
    image: bytes | None = field(default=None, repr=False)  # PDF display equation, cropped from the page (PNG)


@dataclass
class PSection:
    title: str
    paras: list[PPara] = field(default_factory=list)
    level: int = 1
    kind: str | None = None  # None → detected from title


@dataclass
class ParsedDoc:
    title: str
    sections: list[PSection]
    source_type: str
    warning: str | None = None
    concepts: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # what is odd about the file itself, e.g. "hidden_text"

    def non_empty(self) -> "ParsedDoc":
        self.sections = [s for s in self.sections if s.paras or s.title]
        for s in self.sections:
            s.paras = [p for p in s.paras if p.text.strip()]
        self.sections = [s for s in self.sections if s.paras]
        return self


class ImportFailed(Exception):
    """Import could not produce structure; message is shown to the user."""
