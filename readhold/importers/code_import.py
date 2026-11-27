"""Code files: one section per top-level definition, the code kept exactly as written.

The file is read line by line. A line that starts a definition at the left margin (a function, a class, a type)
starts a section; the comments and decorators right above it go with it. In Python, the methods of a class are
sections one level down. What comes before the first definition is "Top of file". Inside a section, blank lines
separate the paragraphs, and every paragraph has the kind "code", so the reader shows it in a fixed-width block
and the pacer leaves it alone. Nothing is run and nothing is interpreted: this only looks at the text of lines.
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import ImportFailed, ParsedDoc, PPara, PSection

CODE_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
    ".go": "go", ".rs": "rust",
    ".java": "c", ".c": "c", ".h": "c", ".cpp": "c", ".cc": "c", ".hpp": "c", ".cs": "c", ".kt": "c", ".swift": "c", ".php": "c",
    ".rb": "ruby", ".sh": "shell", ".ps1": "shell", ".sql": "plain", ".css": "plain", ".json": "plain", ".toml": "plain",
    ".yaml": "plain", ".yml": "plain",
}

NAME = r"([A-Za-z_$][\w$]*)"
# (pattern, title) per language: the pattern is tried on a line at the left margin; \1 is the name
RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "python": [(re.compile(rf"(?:async\s+)?def\s+{NAME}"), "def {}"), (re.compile(rf"class\s+{NAME}"), "class {}")],
    "js": [
        (re.compile(rf"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*{NAME}"), "function {}"),
        (re.compile(rf"(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+{NAME}"), "class {}"),
        (re.compile(rf"(?:export\s+)?(?:declare\s+)?interface\s+{NAME}"), "interface {}"),
        (re.compile(rf"(?:export\s+)?(?:declare\s+)?type\s+{NAME}\s*[=<]"), "type {}"),
        (re.compile(rf"(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+{NAME}"), "enum {}"),
        (re.compile(rf"(?:export\s+)?(?:const|let|var)\s+{NAME}\s*(?::[^=]+)?=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)"), "const {}"),
    ],
    "go": [(re.compile(rf"func\s+(?:\([^)]*\)\s*)?{NAME}"), "func {}"), (re.compile(rf"type\s+{NAME}"), "type {}")],
    "rust": [
        (re.compile(rf"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+{NAME}"), "fn {}"),
        (re.compile(rf"(?:pub(?:\([^)]*\))?\s+)?(struct|enum|trait|mod|union)\s+{NAME}"), "{} {}"),
        (re.compile(r"impl\b[^{]*?([A-Za-z_]\w*)\s*(?:<[^{]*>)?\s*\{?\s*$"), "impl {}"),
    ],
    "c": [
        (re.compile(rf"(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|export)\s+)*(class|interface|struct|enum|namespace|record|object|protocol|extension|trait)\s+{NAME}"), "{} {}"),
        (re.compile(rf"(?:(?:public|private|protected|internal|static|final|override|suspend|inline)\s+)*(?:fun|func|function)\s+{NAME}"), "function {}"),
        # a C-like function: a return type, a name, an opening bracket, and no semicolon at the end of the line
        (re.compile(rf"(?!(?:if|for|while|switch|return|else|do|catch|using|typedef)\b)[A-Za-z_][\w\s\*&:<>,\[\]~]*?\b{NAME}\s*\([^;]*$"), "function {}"),
    ],
    "ruby": [(re.compile(r"def\s+([\w.?!]+)"), "def {}"), (re.compile(rf"(class|module)\s+{NAME}"), "{} {}")],
    "shell": [(re.compile(rf"(?:function\s+)?{NAME}\s*\(\)\s*\{{?"), "function {}"), (re.compile(r"function\s+([\w-]+)"), "function {}")],
    "plain": [],
}
LEAD = re.compile(r"\s*(#|//|/\*|\*|@|--|\[\s*[A-Za-z])")  # a comment, a decorator or an attribute: it belongs to what follows
PY_METHOD = re.compile(rf"(?:async\s+)?def\s+{NAME}")


MAX_HEADING_LINE = 1_000  # characters: a longer line is not a heading, and is not run through the patterns (time)


def _title(rules: list[tuple[re.Pattern, str]], line: str) -> str | None:
    if len(line) > MAX_HEADING_LINE:
        return None
    for pattern, title in rules:
        m = pattern.match(line)
        if m:
            return title.format(*m.groups())
    return None


def _paras(lines: list[str]) -> list[PPara]:
    """Blank lines separate paragraphs; the lines themselves are untouched."""
    out, cur = [], []
    for line in [*lines, ""]:
        if line.strip():
            cur.append(line)
        elif cur:
            out.append(PPara("\n".join(cur), "code"))
            cur = []
    return out


def parse_code(text: str, filename: str) -> ParsedDoc:
    lang = CODE_EXT.get(Path(filename).suffix.lower(), "plain")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any(line.strip() for line in lines):
        raise ImportFailed("The file is empty.")
    rules = RULES[lang]
    # where each section starts: (line index, title, level)
    starts: list[tuple[int, str, int]] = []
    owner = ""  # the Python class we are inside, for its methods
    body_indent = ""  # the indent of that class body, taken from its first line
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        at_margin = not line[0].isspace()
        if at_margin:
            title = _title(rules, line)
            if title:
                starts.append((i, title, 1))
                owner = title[6:] if lang == "python" and title.startswith("class ") else ""
                body_indent = ""
            elif not LEAD.match(line) and not line.startswith((")", "]", "}")):
                owner = ""  # ordinary code at the margin: the class has ended
        elif owner and lang == "python":
            indent = line[:len(line) - len(line.lstrip())]
            body_indent = body_indent or indent  # the class body sets the indent: 4 spaces, 2 spaces or a tab
            m = PY_METHOD.match(line.lstrip())
            if m and indent == body_indent:
                starts.append((i, f"{owner}.{m.group(1)}", 2))
    # the comments and decorators right above a definition go with it
    moved: list[tuple[int, str, int]] = []
    floor = 0
    for i, title, level in starts:
        j = i
        while j - 1 >= floor and lines[j - 1].strip() and LEAD.match(lines[j - 1]) and (level == 2 or not lines[j - 1][0].isspace()):
            j -= 1
        moved.append((j, title, level))
        floor = i + 1
    sections: list[PSection] = []
    if not moved:
        sections.append(PSection(title=filename, paras=_paras(lines), kind="other"))
    else:
        if moved[0][0] > 0:
            sections.append(PSection(title="Top of file", paras=_paras(lines[:moved[0][0]]), kind="other"))
        for n, (start, title, level) in enumerate(moved):
            end = moved[n + 1][0] if n + 1 < len(moved) else len(lines)
            sections.append(PSection(title=title[:200], paras=_paras(lines[start:end]), level=level, kind="other"))
    doc = ParsedDoc(title=filename, sections=sections, source_type="code").non_empty()
    if not doc.sections:
        raise ImportFailed("The file is empty.")
    return doc
