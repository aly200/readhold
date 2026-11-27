"""Markdown and plain text: headings become sections, backtick terms become concepts, code set aside."""
from __future__ import annotations

import re

import mistune

from ..text import looks_like_heading
from .model import ParsedDoc, PPara, PSection

_md = mistune.create_markdown(renderer=None, plugins=["table", "strikethrough", "math"])


def _looks_like_money(raw: str) -> bool:
    """`$5 and $` from "$5 and $10": a number followed by words, with no LaTeX in it."""
    return bool(re.match(r"^\d[\d,.]*\s", raw)) and "\\" not in raw and not re.search(r"[=^_{}]", raw)


def _inline_text(children: list[dict] | None, concepts: list[str]) -> str:
    out: list[str] = []
    for c in children or []:
        t = c.get("type")
        if t == "text":
            out.append(c.get("raw", ""))
        elif t == "codespan":
            raw = c.get("raw", "")
            if 1 < len(raw) < 40:
                concepts.append(raw)
            out.append(raw)
        elif t in ("softbreak", "linebreak"):
            out.append(" ")
        elif t == "inline_math":
            raw = c.get("raw", "")
            if _looks_like_money(raw):
                out.append(f"${raw}$")  # "$5 and $10" is prices, not a formula
            else:
                out.append(f"\\({raw.strip()}\\)")
        elif t == "image":
            alt = _inline_text(c.get("children"), concepts)
            if alt:
                out.append(f"[image: {alt}]")
        else:
            out.append(_inline_text(c.get("children"), concepts) or c.get("raw", ""))
    return "".join(out)


def parse_markdown(source: str, fallback_title: str = "Untitled") -> ParsedDoc:
    tokens = _md(source)
    concepts: list[str] = []
    title = None
    sections: list[PSection] = [PSection(title="Start")]

    def walk(nodes: list[dict]) -> None:
        nonlocal title
        for tok in nodes:
            t = tok.get("type")
            if t == "heading":
                text = _inline_text(tok.get("children"), concepts).strip()
                level = tok.get("attrs", {}).get("level", 1)
                if level == 1 and title is None and not any(s.paras for s in sections):
                    title = text
                    continue
                sections.append(PSection(title=text or "Section", level=level))
            elif t == "paragraph":
                text = _inline_text(tok.get("children"), concepts).strip()
                sections[-1].paras.append(PPara(text))
            elif t == "block_code":
                sections[-1].paras.append(PPara(tok.get("raw", "").rstrip(), "code"))
            elif t == "block_math":
                tex = tok.get("raw", "").strip()
                tag = re.search(r"\\tag\{([^{}]+)\}", tex)
                tex = re.sub(r"\\tag\{[^{}]+\}", "", tex).strip()
                if tex:
                    sections[-1].paras.append(PPara(f"\\[{tex}\\]" + (f" ({tag.group(1)})" if tag else ""), "equation"))
            elif t == "list":
                for item in tok.get("children", []):
                    text = " ".join(
                        _inline_text(ch.get("children"), concepts).strip()
                        for ch in item.get("children", [])
                        if ch.get("type") in ("block_text", "paragraph")
                    ).strip()
                    if text:
                        if not re.search(r"[.!?:]$", text):
                            text += "."
                        sections[-1].paras.append(PPara(text, "list"))
                    nested = [ch for ch in item.get("children", []) if ch.get("type") == "list"]
                    walk(nested)
            elif t == "block_quote":
                walk(tok.get("children", []))
            elif t == "table":
                rows = []
                for part in tok.get("children", []):
                    for row in part.get("children", []) if part.get("type") != "table_head" else [part]:
                        cells = [_inline_text(c.get("children"), concepts).strip() for c in row.get("children", [])]
                        rows.append(" | ".join(cells))
                sections[-1].paras.append(PPara("\n".join(rows), "code"))
            elif t == "block_html":
                continue  # untrusted markup is dropped, never rendered

    walk(tokens)
    doc = ParsedDoc(title=title or fallback_title, sections=sections, source_type="markdown")
    doc.concepts = sorted(set(concepts), key=str.lower)
    if not sections[0].paras:
        sections.pop(0)
    elif len(sections) > 1 or title:
        sections[0].title = "Opening"
    return doc.non_empty()


def parse_text(source: str, fallback_title: str = "Untitled") -> ParsedDoc:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", source.replace("\r\n", "\n")) if b.strip()]
    sections = [PSection(title="Opening")]
    title = None
    for i, block in enumerate(blocks):
        lines = block.split("\n")
        if len(lines) == 1 and looks_like_heading(lines[0]):
            if i == 0 and title is None:
                title = lines[0].strip()
                continue
            sections.append(PSection(title=lines[0].strip()))
            continue
        if len(lines) > 1 and looks_like_heading(lines[0]) and len(lines[0]) < 60:
            sections.append(PSection(title=lines[0].strip()))
            block = "\n".join(lines[1:])
        sections[-1].paras.append(PPara(block))
    doc = ParsedDoc(title=title or fallback_title, sections=sections, source_type="text")
    return doc.non_empty()
