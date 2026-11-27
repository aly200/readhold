"""Parser tests. Synthetic fixtures always run; put your own real files in tests/fixtures/real/ to test them too."""
from pathlib import Path

from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas
import pytest

from readhold.importers import import_bytes
from readhold.importers.markdown_import import parse_markdown, parse_text
from readhold.importers.model import ImportFailed
from readhold.importers.pdf_import import parse_pdf
from readhold.store import load_document

REAL = Path(__file__).parent / "fixtures" / "real"


def test_markdown_structure(sample_md):
    doc = parse_markdown(sample_md, "x")
    assert doc.title == "Attention Is a Test"
    titles = [s.title for s in doc.sections]
    assert titles == ["Abstract", "Introduction", "Related Work", "Method", "Results", "References"]
    method = doc.sections[3]
    assert [p.kind for p in method.paras] == ["text", "code"]
    assert "top-k" in doc.concepts


def test_markdown_drops_html():
    doc = parse_markdown("# T\n\n<script>alert(1)</script>\n\nSafe text here.", "x")
    texts = [p.text for s in doc.sections for p in s.paras]
    assert texts == ["Safe text here."]


def test_plain_text_headings():
    doc = parse_text("My Notes\n\n1. Introduction\n\nFirst para. Second sentence.\n\n2. Method\n\nWe did things.", "x")
    assert doc.title == "My Notes"
    assert [s.title for s in doc.sections] == ["1. Introduction", "2. Method"]


H = 792  # page height; positions below are measured from the top, like the parser's


def _text(c: canvas.Canvas, x: float, y: float, text: str, size: float, bold: bool = False) -> None:
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, H - y, text)


def _textbox(c: canvas.Canvas, x0: float, y0: float, x1: float, text: str, size: float) -> None:
    for i, line in enumerate(simpleSplit(text, "Helvetica", size, x1 - x0)):
        _text(c, x0, y0 + size + i * size * 1.2, line, size)


def _make_two_column_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=(612, H))
    _text(c, 150, 70, "A Study of Columns", 20, bold=True)
    _text(c, 72, 110, "Abstract", 13, bold=True)
    _textbox(c, 72, 118, 540, "We study reading order in two column papers. The main result is that order matters.", 10)
    left = "Reading order breaks when columns are merged naively. This column is the left one and it should come first."
    right = "The right column continues the story. It should come after the left column text."
    _text(c, 72, 200, "1 Introduction", 13, bold=True)
    _textbox(c, 72, 210, 296, left, 10)
    _text(c, 316, 200, "2 Method", 13, bold=True)
    _textbox(c, 316, 210, 540, right, 10)
    _textbox(c, 72, 420, 296, "Figure 1: A diagram of two columns.", 8)
    _text(c, 72, 770, "Preprint", 8)
    c.showPage()
    _text(c, 72, 80, "References", 13, bold=True)
    _textbox(c, 72, 90, 540, "[1] A. Person. A paper. 2020. [2] B. Person. Another paper. 2021.", 10)
    _text(c, 72, 770, "Preprint", 8)
    c.showPage()
    c.save()


def _make_table_pdf(path: Path) -> None:
    """A paragraph, a table, a hyphenated word across lines, and a footnote."""
    c = canvas.Canvas(str(path), pagesize=(612, H))
    _text(c, 150, 70, "Tables and Footnotes", 20, bold=True)
    _text(c, 72, 110, "1 Results", 13, bold=True)
    _text(c, 72, 135, "Our model is fast and the results are shown in the table below, which is surpris-", 10)
    _text(c, 72, 147, "ingly clear about the main finding of this short study.", 10)
    for i, row in enumerate([("Model", "BLEU", "Cost"), ("Base", "27.3", "3.3"), ("Big", "28.4", "2.3")]):
        for j, cell in enumerate(row):
            _text(c, 120 + j * 120, 180 + i * 14, cell, 10)
    _text(c, 72, 240, "We then discuss what the numbers mean for readers of long papers.", 10)
    _text(c, 72, 700, "1This footnote explains a detail in smaller print.", 8)
    c.showPage()
    c.save()


def test_pdf_two_columns_and_sections(tmp_path):
    f = tmp_path / "cols.pdf"
    _make_two_column_pdf(f)
    doc = parse_pdf(str(f))
    assert doc.title == "A Study of Columns"
    titles = [s.title for s in doc.sections]
    assert titles[:3] == ["Abstract", "1 Introduction", "2 Method"]
    assert "References" in titles
    intro = " ".join(p.text for p in doc.sections[1].paras)
    assert "left one" in intro and "right column" not in intro
    all_text = " ".join(p.text for s in doc.sections for p in s.paras)
    assert "Preprint" not in all_text  # running footer removed
    refs = next(s for s in doc.sections if s.title == "References")
    assert [p.kind for p in refs.paras] == ["reference", "reference"]
    kinds = {p.kind for s in doc.sections for p in s.paras if p.text.startswith("Figure 1")}
    assert kinds == {"caption"}


def test_pdf_tables_hyphens_footnotes(tmp_path):
    f = tmp_path / "table.pdf"
    _make_table_pdf(f)
    doc = parse_pdf(str(f))
    results = next(s for s in doc.sections if s.title == "1 Results")
    texts = [p.text for p in results.paras if p.kind == "text"]
    assert any("surprisingly clear" in t for t in texts)  # hyphen across the line break is joined
    assert any(t.startswith("We then discuss") for t in texts)
    assert not any("27.3" in t for t in texts)  # table cells are not paced as prose
    assert any("27.3" in p.text for p in results.paras if p.kind == "fragment")
    assert any(p.kind == "caption" and "footnote explains" in p.text for p in results.paras)


def test_failed_pdf_falls_back_and_keeps_original(db, home):
    result = import_bytes(db, "broken.pdf", b"%PDF-1.4 not really a pdf")
    d = load_document(db, result["id"])
    assert d["import_warning"]
    assert d["source_type"] == "plain"
    assert list((home / "library").glob("*.pdf"))


@pytest.mark.parametrize("path", sorted(REAL.glob("*")) if REAL.exists() else [], ids=lambda p: p.name)
def test_real_files_import(db, path):
    """Your own course PDFs, articles and notes: each must import with sections and readable sentences."""
    result = import_bytes(db, path.name, path.read_bytes())
    d = load_document(db, result["id"])
    assert result["sentences"] > 10, "almost no text came out"
    assert not d["import_warning"] or len(d["sections"]) >= 1


def test_password_pdf_is_reported(tmp_path):
    f = tmp_path / "locked.pdf"
    c = canvas.Canvas(str(f), encrypt="secret")
    _text(c, 72, 100, "Hidden text behind a password.", 10)
    c.save()
    with pytest.raises(ImportFailed, match="password"):
        parse_pdf(str(f))
