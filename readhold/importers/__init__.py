"""Import entry points: a file you pick or drop, or text you paste. Nothing is downloaded.
Every path ends in store.save_parsed(). Failures fall back to a plain view."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .. import config
from ..db import DB
from ..store import save_parsed
from .code_import import CODE_EXT, parse_code
from .markdown_import import parse_markdown, parse_text
from .model import ImportFailed, ParsedDoc, PPara, PSection
from .pdf_import import TooManyPages, parse_pdf, plain_text

log = logging.getLogger(__name__)

TEXT_EXT = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".text": "text", ".rst": "text"}


def keep_original(data: bytes, ext: str) -> str:
    digest = hashlib.sha256(data).hexdigest()
    target = config.library_dir() / f"{digest}{ext}"
    if not target.exists():
        target.write_bytes(data)
    return digest


def _plain_fallback(title: str, text: str, reason: str) -> ParsedDoc:
    paras = [PPara(p.strip()) for p in text.split("\n\n") if p.strip()] or [PPara(reason)]
    return ParsedDoc(title=title, sections=[PSection("Text", paras)], source_type="plain", warning=reason)


def import_bytes(db: DB, filename: str, data: bytes, why: str = "") -> dict:
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem.replace("_", " ").strip() or "Untitled"
    if ext != ".pdf" and ext not in TEXT_EXT and ext not in CODE_EXT and ext != "":
        raise ImportFailed(f"Unsupported file type '{ext}'. Use PDF, Markdown, text or a code file.")  # nothing is stored for it
    digest = keep_original(data, ext)
    if ext == ".pdf":
        path = config.library_dir() / f"{digest}{ext}"
        try:
            doc = parse_pdf(str(path), fallback_title=stem)
        except ImportFailed as e:
            try:
                text = plain_text(str(path))
            except Exception:  # noqa: BLE001
                text = ""
            doc = _plain_fallback(stem, text, str(e))
            if text.strip() and not isinstance(e, TooManyPages):
                doc.flags.append("hidden_text")  # the parser saw nothing a reader could read, yet the file holds text
        except Exception as e:  # noqa: BLE001
            log.exception("PDF import crashed for %s", filename)
            doc = _plain_fallback(stem, "", f"The PDF parser failed ({e.__class__.__name__}). The original file is kept.")
    elif ext in CODE_EXT:
        text = data.decode("utf-8", errors="replace")
        try:
            doc = parse_code(text, Path(filename).name)
        except ImportFailed as e:
            doc = _plain_fallback(stem, text, str(e))
    else:  # a text extension or none: the check above let nothing else through
        text = data.decode("utf-8", errors="replace")
        doc = parse_markdown(text, stem) if TEXT_EXT.get(ext) == "markdown" else parse_text(text, stem)
        if not doc.sections:
            doc = _plain_fallback(stem, text, "The file looks empty.")
    return save_parsed(db, doc, source=filename, file_hash=digest, why=why)


def import_text(db: DB, title: str, text: str, fmt: str = "markdown", why: str = "") -> dict:
    title = title.strip() or "Pasted text"
    doc = parse_markdown(text, title) if fmt == "markdown" else parse_text(text, title)
    if not doc.sections:
        raise ImportFailed("There is no text to import.")
    digest = keep_original(text.encode("utf-8"), ".md" if fmt == "markdown" else ".txt")
    return save_parsed(db, doc, source="pasted", file_hash=digest, why=why)
