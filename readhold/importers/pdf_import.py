"""PDF import with pypdfium2 (PDFium; Apache-2.0/BSD): headings from font size, keyword sections,
two-column order by x-position.

PDFium gives characters with boxes, sizes and fonts. This module groups them into lines, then lines
into blocks (paragraphs, headings), then reads the blocks in column order.
"""
from __future__ import annotations

import ctypes
import re
import threading
from collections import Counter
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as pr

from ..text import normalize_ws, section_kind
from .model import ImportFailed, ParsedDoc, PPara, PSection

# PDFium is not thread-safe, and the server renders and imports in worker threads: every PDFium call
# in the app goes through this one lock.
PDFIUM_LOCK = threading.RLock()

KEYWORD_HEADINGS = re.compile(
    r"^((\d+(\.\d+)*\.?|[IVX]+\.|[A-Z]\.)\s+)?(abstract|introduction|background|related work|method(s|ology)?|"
    r"approach|experiments?|results|evaluation|discussion|conclusions?|references|bibliography|"
    r"acknowledg(e)?ments?|appendix)\b",
    re.IGNORECASE,
)
NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+){0,3}\.?|[IVX]+\.|[A-H]\.)\s+[A-Z][^.]{1,80}$")
CAPTION = re.compile(r"^(fig(ure)?|table|tab|algorithm|listing)\.?\s*\d+[.:]?", re.IGNORECASE)
MATH_CHARS = re.compile(r"[=∑∏∫√∞≈≠≤≥∈∀∃∂∇±×÷αβγδεθλμσφψωΣΠΔΩ]")
BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi|-medi|cmbx|cmb\d|\.b$", re.IGNORECASE)
LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "­": ""})
TWO_PI = 6.2832
SECTION_NUMBER = re.compile(r"(\d+(\.\d+)*\.?|[IVX]+\.|[A-H]\.)")
MAX_PAGES = 3_000  # a longer PDF opens as the plain text of its first pages, with the reason (the whole parse holds PDFIUM_LOCK)


class TooManyPages(ImportFailed):
    """Not a PDF that hides text: one too long to read the structure of."""
TABLE_SEGS = 3  # a row with two or more wide gaps is a table row; one gap is a run-in heading ("Encoder:  The…")
PROSE_WORD = re.compile(r"\b[A-Za-z]{3,}\b")


@dataclass
class Block:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    bold: bool
    lines: int
    tabular: bool = False  # rows of separate cells: a table or a figure's labels
    image: bytes | None = None  # a display equation: PNG cropped from the page


@dataclass
class _Line:
    x0: float = 1e9
    y0: float = 1e9
    x1: float = -1e9
    y1: float = -1e9
    text: str = ""
    sizes: Counter = field(default_factory=Counter)
    bold: int = 0
    total: int = 0
    rotated: int = 0
    space: bool = False
    hyphen: bool = False
    segs: int = 1  # pieces joined on one baseline across wide gaps (table cells)

    def add(self, ch: str, box: tuple[float, float, float, float], size: float, bold: bool, rotated: bool) -> None:
        if self.space and self.text and not self.text.endswith(" "):
            self.text += " "
        self.space = False
        self.text += ch
        x0, y0, x1, y1 = box
        self.x0, self.y0, self.x1, self.y1 = min(self.x0, x0), min(self.y0, y0), max(self.x1, x1), max(self.y1, y1)
        self.sizes[round(size, 1)] += 1
        self.total += 1
        self.bold += bold
        self.rotated += rotated

    @property
    def size(self) -> float:
        return self.sizes.most_common(1)[0][0] if self.sizes else 0.0

    def join(self, other: _Line) -> None:
        """Another piece of this row, further right on the same baseline."""
        self.text = self.text.rstrip() + " " + other.text.lstrip()
        self.x0, self.y0 = min(self.x0, other.x0), min(self.y0, other.y0)
        self.x1, self.y1 = max(self.x1, other.x1), max(self.y1, other.y1)
        self.sizes.update(other.sizes)
        self.bold += other.bold
        self.total += other.total
        self.rotated += other.rotated
        self.hyphen = other.hyphen
        self.segs += other.segs


def _font_is_bold(textpage, i: int, cache: dict) -> bool:
    obj = pr.FPDFText_GetTextObject(textpage, i)
    if not obj:
        return False
    font = pr.FPDFTextObj_GetFont(obj)
    key = ctypes.cast(font, ctypes.c_void_p).value if font else None
    if key in cache:
        return cache[key]
    bold = False
    if font:
        name = ""
        n = pr.FPDFFont_GetBaseFontName(font, None, 0)
        if n:
            buf = ctypes.create_string_buffer(n)
            pr.FPDFFont_GetBaseFontName(font, buf, n)
            name = buf.value.decode("utf-8", "replace")
        bold = pr.FPDFFont_GetWeight(font) >= 600 or bool(BOLD_FONT.search(name))
    cache[key] = bold
    return bold


# Text a reader cannot see. Characters that are far too small or off the page are dropped. White (or fully
# transparent) characters are kept, because white text on a coloured band is ordinary, but they are counted.
# _parse_pdf resets the counts and turns them into the "hidden_text" flag. PDFIUM_LOCK makes this safe.
UNSEEN = {"dropped": 0, "pale": 0}
TOO_SMALL_PT = 1.0
FLAG_AT = 15  # characters


def _lines(page: pdfium.PdfPage) -> list[_Line]:
    """Characters → lines, in PDFium's reading order. A line ends where PDFium puts a line break,
    where the baseline jumps, or where a wide gap separates two columns."""
    height = page.get_height()
    width = page.get_width()
    textpage = page.get_textpage()
    red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
    loose = pr.FS_RECTF()
    raw = textpage.raw
    fonts: dict = {}
    out: list[_Line] = []
    cur: _Line | None = None
    broke = False  # PDFium put a line break here; honoured unless the text continues on the same visual line
    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    try:
        for i in range(pr.FPDFText_CountChars(raw)):
            code = pr.FPDFText_GetUnicode(raw, i)
            ch = chr(code) if code else ""
            if ch in ("\r", "\n"):
                broke = True
                continue
            if code == 2:  # PDFium's marker for a hyphen at a line break ("sur-" / "prisingly")
                if cur is not None:
                    cur.text = cur.text.rstrip() + "-"
                    cur.hyphen = True
                continue
            if not ch or code < 32 or ch.isspace():
                if cur is not None:
                    cur.space = True
                continue
            if not pr.FPDFText_GetCharBox(raw, i, left, right, bottom, top):
                continue
            size = pr.FPDFText_GetFontSize(raw, i)
            box = (left.value, height - top.value, right.value, height - bottom.value)
            # the height the glyph has on the page: a 0.5 pt font scaled up is readable, a 12 pt font scaled to nothing is not
            seen = abs(loose.top - loose.bottom) if pr.FPDFText_GetLooseCharBox(raw, i, loose) else size
            if size > 0 and not 0.5 <= seen / size <= 2:
                size = seen  # the font is drawn scaled: spacing and headings go by the size on the page
            if 0 < seen < TOO_SMALL_PT or box[2] < 0 or box[0] > width or box[3] < 0 or box[1] > height:
                UNSEEN["dropped"] += 1  # nobody can read it on the page, so it is not part of the document
                continue
            if pr.FPDFText_GetFillColor(raw, i, red, green, blue, alpha) and (alpha.value <= 8 or min(red.value, green.value, blue.value) >= 250):
                UNSEEN["pale"] += 1
            if cur is not None and cur.total:
                em = max(size, cur.size)
                mid = (box[1] + box[3]) / 2
                # stacked scripts (W with ^Q over _i) start left of the previous small glyph
                back = em * (1.2 if size < cur.size * 0.85 else 0.5)
                beside = cur.x1 - back <= box[0] <= cur.x1 + em * 3
                # superscripts and subscripts sit a little above or below, but still on this line
                on_line = cur.y0 - em * 0.45 <= mid <= cur.y1 + em * 0.45
                if not (beside and on_line):
                    out.append(cur)
                    cur = None
                elif broke and box[0] > cur.x1 + em * 0.15:
                    cur.space = True
                elif box[0] - cur.x1 > em * 1.0 and not SECTION_NUMBER.fullmatch(cur.text.strip()):
                    cur.segs += 1  # a wide gap inside a line: table cells, not prose
                    cur.space = True
            broke = False
            if cur is None:
                cur = _Line()
            angle = pr.FPDFText_GetCharAngle(raw, i)
            rotated = angle > 0.1 and abs(angle - TWO_PI) > 0.1
            cur.add(ch.translate(LIGATURES) or ch, box, size, _font_is_bold(raw, i, fonts), rotated)
            cur.hyphen = ch in "-­" or bool(pr.FPDFText_IsHyphen(raw, i))
        if cur is not None and cur.total:
            out.append(cur)
    finally:
        textpage.close()
    # rotated text (e.g. the arXiv margin stamp) is not body text
    return [ln for ln in out if ln.rotated * 2 < ln.total and ln.text.strip()]


def _same_block(blk: list[_Line], ln: _Line) -> bool:
    last = blk[-1]
    em = max(last.size, 1.0)
    x0, x1 = min(b.x0 for b in blk), max(b.x1 for b in blk)
    if abs(ln.size - last.size) > max(0.6, em * 0.08):
        return False  # a size change: heading ↔ body, body ↔ caption
    if (ln.segs >= TABLE_SEGS) != (last.segs >= TABLE_SEGS):
        return False  # table rows and prose lines don't share a block
    gap = ln.y0 - last.y1
    if gap > em * 0.65 or gap < -em * 0.5:
        return False
    if ln.x1 < x0 or ln.x0 > x1:
        return False  # no horizontal overlap: another column
    centered = em * 2.5
    if ln.x0 > x0 + centered and ln.x1 < x1 - centered and _line_mathy(ln.text):
        return False  # a centred formula line under full-width text: a displayed equation starts
    if last.x0 > ln.x0 + centered and last.x1 < ln.x1 - centered and _line_mathy(last.text):
        return False  # full-width text after a centred formula line: the equation has ended
    if len(blk) == 1 and last.bold == last.total and ln.bold * 2 < ln.total:
        return False  # a bold heading line followed by normal text
    ends_sentence = bool(re.search(r"[.!?:]$", last.text.strip()))
    if ends_sentence and (ln.x0 > x0 + em * 0.8 or last.x1 < x1 - em * 3):
        return False  # paragraph break: indented first line, or a short last line
    return True


def _make_block(lines: list[_Line], pno: int) -> Block:
    texts = [ln.text.strip() for ln in lines]
    merged = list(texts)
    for k in range(len(merged) - 1):  # "represen-" / "tations of" → "representations" / "of"
        a, nxt = merged[k], merged[k + 1]
        if len(a) > 2 and a.endswith("-") and a[-2].isalpha() and nxt[:1].islower():
            word, _, rest = nxt.partition(" ")
            merged[k] = a[:-1] + word
            merged[k + 1] = rest
    merged = [x for x in merged if x]
    sizes: Counter = Counter()
    bold = total = 0
    for ln in lines:
        sizes.update(ln.sizes)
        bold += ln.bold
        total += ln.total
    return Block(
        pno,
        min(ln.x0 for ln in lines), min(ln.y0 for ln in lines), max(ln.x1 for ln in lines), max(ln.y1 for ln in lines),
        "\n".join(merged), sizes.most_common(1)[0][0], bold > total * 0.6, len(merged),
        sum(ln.segs >= TABLE_SEGS for ln in lines) * 2 > len(lines),
    )


def _blocks(page: pdfium.PdfPage, pno: int) -> list[Block]:
    rows: list[_Line] = []
    for ln in _lines(page):
        if rows:
            last = rows[-1]
            em = max(ln.size, last.size, 1.0)
            same_baseline = abs(ln.y1 - last.y1) < 2 or abs((ln.y0 + ln.y1) / 2 - (last.y0 + last.y1) / 2) < em * 0.3
            if same_baseline and ln.x0 >= last.x1 - 1:
                last.join(ln)  # "1" + "Introduction", or the cells of one table row
                continue
        rows.append(ln)
    groups: list[list[_Line]] = []
    for ln in rows:
        if groups and _same_block(groups[-1], ln):
            groups[-1].append(ln)
        else:
            groups.append([ln])
    return [_make_block(g, pno) for g in groups]


# ------------------------------------------------------------------ display equations
# A PDF keeps no LaTeX: a formula is glyphs placed on the page (fractions as stacked lines, roots as
# drawn strokes). So display equations are cropped from the page as pictures — exact, like the paper.
EQ_NUMBER = re.compile(r"^\(\s*\d{1,3}[a-z]?\s*\)$")
EQ_NUMBER_END = re.compile(r"\s(\(\d{1,3}[a-z]?\))$")
EQ_RENDER_SCALE = 3  # 216 dpi: crisp at reading size


EQ_SYMBOLS = re.compile(r"[·−∗+/()^_|‖]")


def _math_score(t: str) -> int:
    return len(MATH_CHARS.findall(t)) + len(EQ_SYMBOLS.findall(t))


def _line_mathy(t: str) -> bool:
    """A line that reads like a formula: symbols, and few real words."""
    return _math_score(t) >= 2 and len(PROSE_WORD.findall(t)) <= 4


def _eq_like(b: Block) -> bool:
    """Short, math-looking, not prose: a piece of a displayed formula."""
    t = normalize_ws(b.text)
    if not t or len(t) > 180 or CAPTION.match(t) or len(PROSE_WORD.findall(t)) >= 6:
        return False
    return True


def _eq_seed(b: Block, col: tuple[float, float]) -> tuple[bool, str]:
    """(starts an equation?, its number like "(3)" or ""). `col` is the column's left and right edge."""
    t = normalize_ws(b.text)
    if EQ_NUMBER.match(t):
        return True, t.replace(" ", "")
    if b.tabular or len(t) > 240 or CAPTION.match(t):
        return False, ""
    end = EQ_NUMBER_END.search(t)
    if end and _eq_like(b) and _math_score(EQ_NUMBER_END.sub("", t)) >= 1:
        return True, end.group(1)
    # unnumbered display formula: centred in its column and full of symbols. Function names
    # (sin, pos, Concat) look like words, so centring is the signal, not the word count.
    em = max(b.size, 6.0)
    centred = b.x0 > col[0] + em * 2.5 and b.x1 < col[1] - em * 2.5
    if centred and _math_score(t) >= 4 and len(PROSE_WORD.findall(t)) <= 10:
        return True, ""
    if _eq_like(b) and len(MATH_CHARS.findall(t)) >= 2 and len(PROSE_WORD.findall(t)) <= 3:
        return True, ""
    return False, ""


def _equations(page: pdfium.PdfPage, blocks: list[Block]) -> list[Block]:
    """Group the blocks of each displayed equation, crop it from the page, and replace them by one block."""
    width = page.get_width()
    mid, slack = width / 2, width * 0.04
    paragraphs = [b for b in blocks if b.lines >= 3 and not b.tabular]  # real text, not figure labels
    left = sum(b.x1 <= mid + slack for b in paragraphs)
    right = sum(b.x0 >= mid - slack for b in paragraphs)
    two_col = left >= 1 and right >= 1

    def side(b: Block) -> int:
        return 0 if b.x1 <= mid + slack else 1 if b.x0 >= mid - slack else -1

    def column(b: Block) -> tuple[float, float]:
        s = side(b) if two_col else -1
        same = [p for p in paragraphs if (side(p) == s if s != -1 else True)] or paragraphs
        if not same:
            return 0.0, width
        return min(p.x0 for p in same), max(p.x1 for p in same)

    used: set[int] = set()
    out: list[Block] = []
    for i, seed in enumerate(blocks):
        if i in used:
            continue
        is_seed, number = _eq_seed(seed, column(seed))
        if not is_seed:
            continue
        em = max(seed.size, 6.0)
        group = {i}
        top, bottom = seed.y0, seed.y1
        grew = True
        while grew:
            grew = False
            for j, b in enumerate(blocks):
                if j in group or j in used or not (_eq_like(b) or EQ_NUMBER.match(normalize_ws(b.text))):
                    continue
                if two_col and side(seed) != -1 and side(b) != side(seed):
                    continue
                if b.y0 < bottom + em * 0.35 and b.y1 > top - em * 0.35:
                    group.add(j)
                    top, bottom = min(top, b.y0), max(bottom, b.y1)
                    grew = True
        members = [blocks[j] for j in group]
        if not number:
            number = next((normalize_ws(m.text).replace(" ", "") for m in members if EQ_NUMBER.match(normalize_ws(m.text))), "")
        body = [m for m in members if not EQ_NUMBER.match(normalize_ws(m.text))]
        if not body or bottom - top > em * 14:
            continue  # only a number, or something too tall to be one formula
        x0, x1 = min(m.x0 for m in members), max(m.x1 for m in members)
        image = _crop(page, x0, top, x1, bottom)
        if image is None:
            continue
        text = " ".join(normalize_ws(m.text) for m in sorted(body, key=lambda m: (round(m.y0), m.x0)))
        text = EQ_NUMBER_END.sub("", text).strip()
        used |= group
        out.append(Block(seed.page, x0, top, x1, bottom, f"{text} {number}".strip(), seed.size, False, 1, False, image))
    return [b for k, b in enumerate(blocks) if k not in used] + out


def _crop(page: pdfium.PdfPage, x0: float, y0: float, x1: float, y1: float) -> bytes | None:
    """Render one region of the page as a PNG: dark ink on a transparent background."""
    try:
        import io

        w, h = page.get_width(), page.get_height()
        pad = 3.0
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
        bitmap = page.render(scale=EQ_RENDER_SCALE, crop=(x0, h - y1, w - x1, y0), fill_color=(255, 255, 255, 0))
        try:
            img = bitmap.to_pil()
        finally:
            bitmap.close()
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — a missing picture must never fail the import
        return None


def _column_order(blocks: list[Block], width: float) -> list[Block]:
    """Fix reading order on two-column pages.

    Spanning blocks (title, abstract, wide figures) cut the page into horizontal bands; inside each
    band the left column is read before the right one.
    """
    mid = width / 2
    slack = width * 0.04

    def side(b: Block) -> int:
        if b.x1 <= mid + slack:
            return 0
        if b.x0 >= mid - slack:
            return 1
        return -1  # spans both columns

    ordered: list[Block] = []
    band: list[Block] = []
    for b in sorted(blocks, key=lambda b: (b.y0, b.x0)):
        if side(b) == -1:
            ordered += sorted(band, key=lambda x: (side(x), x.y0))
            band = []
            ordered.append(b)
        else:
            band.append(b)
    ordered += sorted(band, key=lambda x: (side(x), x.y0))
    return ordered


def _is_running_header(b: Block, page_h: float, repeats: Counter) -> bool:
    edge = b.y1 < page_h * 0.07 or b.y0 > page_h * 0.93
    if not edge:
        return False
    key = re.sub(r"\d+", "#", b.text.strip().lower())
    return repeats[key] > 1 or bool(re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", b.text.strip(), re.I))


def _open(path: str) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(path)
    except pdfium.PdfiumError as e:
        if getattr(e, "err_code", None) == pr.FPDF_ERR_PASSWORD:
            raise ImportFailed("This PDF is password-protected.") from e
        raise ImportFailed(f"Could not open the PDF: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise ImportFailed(f"Could not open the PDF: {e}") from e


@dataclass
class _Page:
    width: float
    height: float


def parse_pdf(path: str, fallback_title: str = "Untitled") -> ParsedDoc:
    with PDFIUM_LOCK:
        return _parse_pdf(path, fallback_title)


def _parse_pdf(path: str, fallback_title: str) -> ParsedDoc:
    pdf = _open(path)
    UNSEEN["dropped"] = UNSEEN["pale"] = 0
    try:
        pages: list[tuple[_Page, list[Block]]] = []
        if len(pdf) > MAX_PAGES:
            raise TooManyPages(f"This PDF has {len(pdf):,} pages; Readhold reads the structure of up to {MAX_PAGES:,}. It is shown as the plain text of its first {MAX_PAGES:,} pages; the original file is kept.")
        for pno in range(len(pdf)):
            page = pdf[pno]
            try:
                pages.append((_Page(page.get_width(), page.get_height()), _equations(page, _blocks(page, pno))))
            finally:
                page.close()
        meta_title = (pdf.get_metadata_dict().get("Title") or "").strip()
    finally:
        pdf.close()

    all_blocks = [b for _, bs in pages for b in bs]
    if sum(len(b.text) for b in all_blocks) < 50:
        raise ImportFailed("No selectable text found — this looks like a scanned PDF (OCR is not supported yet).")

    size_hist: Counter = Counter()
    for b in all_blocks:
        size_hist[b.size] += len(b.text)
    body = size_hist.most_common(1)[0][0]

    repeats: Counter = Counter()
    for page, bs in pages:
        for b in bs:
            if b.y1 < page.height * 0.07 or b.y0 > page.height * 0.93:
                repeats[re.sub(r"\d+", "#", b.text.strip().lower())] += 1

    title = None
    first_page_blocks = pages[0][1] if pages else []
    if first_page_blocks:
        top = [b for b in first_page_blocks if b.y0 < pages[0][0].height * 0.4 and len(b.text) < 250]
        if top:
            biggest = max(top, key=lambda b: b.size)
            if biggest.size > body * 1.2:
                title = normalize_ws(biggest.text)
    if not title and meta_title and len(meta_title) > 3 and not meta_title.lower().endswith((".dvi", ".doc", ".tex")):
        title = meta_title
    title = title or fallback_title

    sections: list[PSection] = [PSection(title="Front matter")]
    in_refs = False
    after_refs = False
    seen_headings: set[str] = set()
    for page, bs in pages:
        for b in _column_order(bs, page.width):
            if _is_running_header(b, page.height, repeats):
                continue
            text = normalize_ws(b.text)
            if not text or (text == title and b.page == 0):
                continue
            first_line = normalize_ws(b.text.split("\n", 1)[0])
            words = len(first_line.split())
            heading_like = (
                b.image is None
                and words <= 12
                and len(first_line) < 100
                and (b.lines <= 2 or len(first_line) < 40)
                and first_line.lower() not in seen_headings  # repeated labels (figure text) aren't headings
                and (
                    (b.size >= body * 1.12 and b.lines <= 3)
                    or KEYWORD_HEADINGS.match(first_line) and (b.bold or b.size > body * 1.05 or len(first_line) < 30)
                    or (NUMBERED_HEADING.match(first_line) and (b.bold or b.size > body * 1.02))
                )
            )
            if heading_like:
                rest = normalize_ws(b.text.split("\n", 1)[1]) if "\n" in b.text and b.lines > 1 else ""
                # "Abstract—We propose..." on one line
                inline = re.match(r"^(abstract)\s*[—:.-]\s*(.+)$", first_line, re.I)
                if inline:
                    sections.append(PSection(title="Abstract"))
                    rest = (inline.group(2) + " " + rest).strip()
                elif b.lines > 3 and b.size < body * 1.12 and not rest:
                    heading_like = False
                else:
                    sections.append(PSection(title=first_line.rstrip(".")))
                if heading_like:
                    seen_headings.add(first_line.lower())
                    in_refs = section_kind(sections[-1].title) == "references"
                    after_refs = after_refs or in_refs
                    if after_refs and not in_refs and section_kind(sections[-1].title) == "other":
                        sections[-1].kind = "appendix"  # material after the references is supplementary
                    if rest:
                        sections[-1].paras.append(_para(rest, b, body, in_refs, page.height))
                    continue
            sections[-1].paras.append(_para(text, b, body, in_refs, page.height))

    _numbered_levels(sections)
    doc = ParsedDoc(title=title, sections=sections, source_type="pdf")
    if UNSEEN["dropped"] >= FLAG_AT or UNSEEN["pale"] >= FLAG_AT:
        doc.flags.append("hidden_text")
    if in_refs or any(section_kind(s.title) == "references" for s in sections):
        _split_references(doc)
    doc.non_empty()
    if len(doc.sections) <= 1:
        doc.warning = "No headings were detected; the text is shown as one section. Use Fix structure to split it."
    _merge_broken_paragraphs(doc)
    return doc


def _numbered_levels(sections: list[PSection]) -> None:
    """'6.1 Machine Translation' is level 2 and inherits 'results' from '6 Results' (even if that heading is empty)."""
    kinds: dict[str, str] = {}
    for s in sections:
        m = re.match(r"^(\d+(?:\.\d+)*)\.?\s", s.title)
        if not m:
            continue
        num = m.group(1)
        s.level = min(num.count(".") + 1, 3)
        own = s.kind or section_kind(s.title)
        parent = kinds.get(num.rsplit(".", 1)[0]) if "." in num else None
        if own == "other" and parent:
            s.kind = own = parent
        kinds[num] = own


def _para(text: str, b: Block, body: float, in_refs: bool, page_h: float = 0) -> PPara:
    if in_refs:
        return PPara(text, "reference")
    if b.image is not None:
        return PPara(text, "equation", image=b.image)
    if CAPTION.match(text):
        return PPara(text, "caption")
    symbols = len(MATH_CHARS.findall(text))
    prose = len(PROSE_WORD.findall(text)) >= 8
    if len(text) < 200 and symbols >= 2 and symbols / max(len(text), 1) > 0.03 and not prose:
        return PPara(text, "equation")
    if b.tabular:
        return PPara(text, "fragment")  # table cells and figure labels: shown small, not paced
    if page_h and b.y0 > page_h * 0.7 and b.size < body * 0.95:
        return PPara(text, "caption")  # footnotes: small print low on the page
    if b.size < body * 0.85 and len(text) < 800:
        return PPara(text, "caption")  # footnotes and small print
    if len(text.split()) <= 5 and not re.search(r"[.!?:;]$", text):
        return PPara(text, "fragment")  # labels inside figures, stray lines: shown small, not paced
    return PPara(text)


def _merge_broken_paragraphs(doc: ParsedDoc) -> None:
    """Paragraphs split by a column or page break: join when the first doesn't end a sentence.
    A footnote, caption or table between the two halves stays where it is, after the joined paragraph."""
    for s in doc.sections:
        merged: list[PPara] = []
        for p in s.paras:
            last = next((k for k in range(len(merged) - 1, -1, -1) if merged[k].kind == "text"), None)
            if (
                p.kind == "text"
                and last is not None
                # never across an equation: "We compute [eq] where Q is…" must keep its order
                and all(q.kind in ("caption", "fragment") for q in merged[last + 1:])
                and not re.search(r"[.!?:\"”)]$", merged[last].text)
                and p.text[:1].islower()
            ):
                merged[last] = PPara(merged[last].text + " " + p.text)
            else:
                merged.append(p)
        s.paras = merged


def _split_references(doc: ParsedDoc) -> None:
    for s in doc.sections:
        if section_kind(s.title) != "references":
            continue
        joined = " ".join(p.text for p in s.paras)
        parts = re.split(r"\s(?=\[\d{1,3}\]\s)", " " + joined)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            s.paras = [PPara(p, "reference") for p in parts]
        else:
            s.paras = [PPara(p.text, "reference") for p in s.paras]


def plain_text(path: str) -> str:
    with PDFIUM_LOCK:
        return _plain_text(path)


def _plain_text(path: str) -> str:
    """Last-resort fallback: raw text, page by page."""
    pdf = _open(path)
    try:
        parts = []
        for i, page in enumerate(pdf):
            if i >= MAX_PAGES:  # a bound for the fallback too: the whole read holds PDFIUM_LOCK
                page.close()
                break
            textpage = page.get_textpage()
            parts.append(textpage.get_text_range().replace("\r\n", "\n"))
            textpage.close()
            page.close()
        return "\n\n".join(parts)
    finally:
        pdf.close()
