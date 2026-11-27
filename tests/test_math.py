"""Math in papers: LaTeX kept from Markdown, PDF display equations cropped as pictures."""
from pathlib import Path

from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from readhold.importers.markdown_import import parse_markdown
from readhold.importers.pdf_import import parse_pdf
from readhold.text import count_words, math_to_markdown, split_sentences

PNG = b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ sentences
def test_sentences_never_split_inside_a_formula():
    text = r"We set \(\alpha = 0.5. B\) here. Then \(x\) grows. Done."
    assert split_sentences(text) == [r"We set \(\alpha = 0.5. B\) here.", r"Then \(x\) grows.", "Done."]


def test_formula_counts_as_words_by_length():
    assert count_words(r"Let \(x\) be big.") == 4
    assert count_words(r"Let \(\sum_{i=1}^{n} x_i^2\) be big.") > 4


def test_markdown_export_form():
    assert math_to_markdown(r"See \(x^2\) and \[E = mc^2\].") == "See $x^2$ and $$E = mc^2$$."


# ------------------------------------------------------------------ Markdown
def test_markdown_math():
    doc = parse_markdown("# T\n\nWe have $x^2 + 1$ here. It costs $5 and $10 today.\n\n$$\na = b \\tag{4}\n$$\n", "x")
    paras = doc.sections[0].paras
    assert r"\(x^2 + 1\)" in paras[0].text
    assert "$5 and $10" in paras[0].text  # prices stay prices
    assert paras[1].kind == "equation" and paras[1].text == r"\[a = b\] (4)"


# ------------------------------------------------------------------ PDF
H = 792


def _make_equation_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=(612, H))

    def line(x, y, text, size=10, font="Helvetica"):
        c.setFont(font, size)
        c.drawString(x, H - y, text)

    line(150, 70, "Equations in Papers", 20)
    line(72, 110, "1 Method", 13, "Helvetica-Bold")
    prose = ("We model the output as a straight line through the data points, and the next formula gives it "
             "in full so that the reader can check every term before moving on to the results below.")
    for i, part in enumerate(simpleSplit(prose, "Helvetica", 10, 468)):
        line(72, 135 + i * 12, part)
    line(250, 185, "y = a \u00b7 x + b")
    line(520, 185, "(1)")
    line(72, 215, "where a is the slope and b is the intercept of the fitted line through the points.")
    c.showPage()
    c.save()


def test_pdf_display_equation_is_cropped(tmp_path):
    f = tmp_path / "eq.pdf"
    _make_equation_pdf(f)
    doc = parse_pdf(str(f))
    method = next(s for s in doc.sections if s.title == "1 Method")
    eqs = [p for p in method.paras if p.kind == "equation"]
    assert len(eqs) == 1
    assert eqs[0].image and eqs[0].image.startswith(PNG)
    assert eqs[0].text.endswith("(1)")
    texts = [p.text for p in method.paras if p.kind == "text"]
    assert texts[0].startswith("We model the output") and texts[-1].startswith("where a is the slope")
    assert all("(1)" not in t for t in texts)


def test_equation_picture_is_stored_and_served(client, tmp_path):
    f = tmp_path / "eq.pdf"
    _make_equation_pdf(f)
    r = client.post("/api/import/file", files={"file": ("eq.pdf", f.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    d = client.get(f"/api/documents/{doc_id}").json()
    assets = [p["asset"] for s in d["sections"] for p in s["paragraphs"] if p.get("asset")]
    assert len(assets) == 1
    img = client.get(f"/api/documents/{doc_id}/assets/{assets[0]}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content.startswith(PNG)
    # only names the database knows, only for that document, nothing outside the folder
    assert client.get(f"/api/documents/{doc_id}/assets/{'0' * 32}.png").status_code == 404
    assert client.get(f"/api/documents/{'1' * 32}/assets/{assets[0]}").status_code == 404
    assert client.get(f"/api/documents/{doc_id}/assets/..%2F..%2Freadhold.db").status_code == 404


def test_no_space_before_punctuation_after_formula():
    from readhold.text import normalize_ws

    assert normalize_ws(r"to \(d_k\) , \(d_v\) dims and ( \(x\) ) with \(d\) -dimensional keys.") == (
        r"to \(d_k\), \(d_v\) dims and (\(x\)) with \(d\)-dimensional keys."
    )
