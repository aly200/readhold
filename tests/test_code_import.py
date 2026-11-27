"""Code files become documents: one section per top-level definition, code kept as written (AI plan, phase 0.1)."""
import pytest

from readhold.importers import import_bytes
from readhold.importers.code_import import CODE_EXT, parse_code
from readhold.importers.model import ImportFailed
from readhold.store import load_document

PY = '''"""A tiny router."""
import os
from pathlib import Path

LIMIT = 3


# picks the best block
@cached
def route(blocks, k=LIMIT):
    scored = sorted(blocks)

    return scored[:k]


class Router:
    """Keeps the top blocks."""

    def __init__(self, k):
        self.k = k

    async def run(self, blocks):
        if not blocks:
            return []
        return route(blocks, self.k)


def main():
    print(Router(2).run([3, 1, 2]))
'''

JS = '''import { h } from "./util";

const LIMIT = 3;

// Draws one row.
export function row(item) {
  if (!item) return null;

  return h("li", null, item.title);
}

export const pick = (items) => items.slice(0, LIMIT);

export default class Board {
  constructor(items) {
    this.items = items;
  }
}

interface Item { title: string }
'''

GO = '''package main

import "fmt"

type Router struct {
	k int
}

// Run keeps the top blocks.
func (r *Router) Run(blocks []int) []int {
	if len(blocks) == 0 {
		return nil
	}
	return blocks[:r.k]
}

func main() {
	fmt.Println("hi")
}
'''


def test_python_sections_are_definitions():
    doc = parse_code(PY, "router.py")
    assert doc.title == "router.py" and doc.source_type == "code"
    assert [(s.title, s.level) for s in doc.sections] == [
        ("Top of file", 1), ("def route", 1), ("class Router", 1), ("Router.__init__", 2), ("Router.run", 2), ("def main", 1)]
    assert all(p.kind == "code" for s in doc.sections for p in s.paras)
    route = doc.sections[1]
    assert route.paras[0].text.startswith("# picks the best block\n@cached\ndef route(blocks, k=LIMIT):")  # its comment and decorator stay with it
    assert route.paras[1].text == "    return scored[:k]"  # the indent is kept
    assert "LIMIT = 3" in doc.sections[0].paras[-1].text
    assert doc.sections[4].paras[0].text.startswith("    async def run(self, blocks):")
    # nothing is lost and nothing is repeated
    lines = [line for s in doc.sections for p in s.paras for line in p.text.split("\n")]
    assert lines == [line for line in PY.split("\n") if line.strip()]


def test_javascript_and_go():
    js = parse_code(JS, "board.ts")
    assert [s.title for s in js.sections] == ["Top of file", "function row", "const pick", "class Board", "interface Item"]
    assert js.sections[1].paras[0].text.startswith("// Draws one row.\nexport function row(item) {")
    go = parse_code(GO, "main.go")
    assert [s.title for s in go.sections] == ["Top of file", "type Router", "func Run", "func main"]
    assert go.sections[2].paras[0].text.startswith("// Run keeps the top blocks.")


def test_a_file_without_definitions_is_one_section():
    doc = parse_code("SELECT 1;\n\nSELECT 2;\n", "q.sql")
    assert [s.title for s in doc.sections] == ["q.sql"] and len(doc.sections[0].paras) == 2
    with pytest.raises(ImportFailed):
        parse_code("  \n\n", "empty.py")


def test_long_lines_and_tabs_survive():
    doc = parse_code("def f():\n\treturn '" + "x" * 5000 + "'\n", "long.py")
    assert doc.sections[0].paras[0].text.split("\n")[1].startswith("\treturn 'xxx")


def test_import_and_read_back(db, home):
    assert ".py" in CODE_EXT and ".ts" in CODE_EXT and ".exe" not in CODE_EXT
    result = import_bytes(db, "router.py", PY.encode("utf-8"), why="learn the router")
    d = load_document(db, result["id"])
    assert d["source_type"] == "code" and [s["title"] for s in d["sections"]][:2] == ["Top of file", "def route"]
    par = d["sections"][1]["paragraphs"][1]
    assert par["kind"] == "code" and par["sentences"][0]["text"] == "    return scored[:k]"  # stored with its indent
    assert list((home / "library").glob("*.py"))  # the original file is kept
    with pytest.raises(ImportFailed, match="Unsupported"):
        import_bytes(db, "tool.exe", b"MZ", "")


def test_methods_are_found_with_any_indent():
    two = "class A:\n  x = 1\n\n  def f(self):\n    return 1\n\n  def g(self):\n    def inner():\n      return 2\n    return inner\n"
    assert [s.title for s in parse_code(two, "a.py").sections] == ["class A", "A.f", "A.g"]  # a nested function is not a method
    tab = "class B:\n\tdef f(self):\n\t\treturn 1\n"
    assert [s.title for s in parse_code(tab, "b.py").sections] == ["class B", "B.f"]
