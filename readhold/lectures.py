"""Lectures: PDF slides, PowerPoint decks and HTML pages, shown as pages (not reflowed into text),
with a notebook of notes in several forms and digital-pen ink.

Safety rules:
- Uploads are checked by content, not just by name: a PDF must start with %PDF, a .pptx must be a zip
  with a PowerPoint inside and no zip bomb (entry count and total size are capped before parsing).
- PowerPoint is turned into JSON (positioned text, tables, raster images). Text is rendered with
  textContent in the app; vector images (EMF, WMF, SVG) are skipped, never served.
- HTML lectures run in a sandboxed iframe (no same-origin) under a CSP that allows inline script for
  interactivity but no network at all (connect-src 'none', no remote scripts, images or fonts).
- PDF pages are rendered by PDFium behind the shared PDFIUM_LOCK (PDFium isn't thread-safe).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .bodies import Body
from . import config
from .compass import need_row
from .db import DB, new_id, now
from .importers import keep_original
from .importers.model import ImportFailed

log = logging.getLogger(__name__)

KINDS = {".pdf": "pdf", ".pptx": "pptx", ".html": "html", ".htm": "html"}
MAX_ZIP_ENTRIES = 5000
MAX_ZIP_TOTAL = 400 * 1024 * 1024  # uncompressed bytes a deck may expand to
RASTER = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "bmp": "bmp"}
RENDER_WIDTHS = (480, 960, 1400, 2000)
EMU_PER_PT = 12700

# The only CSP an HTML lecture runs under (see server middleware). Inline script/style for interactive
# lecture pages; nothing can be fetched; it can't be framed by anything but the app.
SANDBOX_CSP = (
    # `sandbox` makes the page an opaque origin even if it is opened directly (not just in the iframe),
    # so its scripts can never read Readhold's pages or API, and it can't open windows or submit forms.
    "sandbox allow-scripts; "
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
    "font-src data:; media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'"
)


# Added to every HTML lecture so the pen can write over it: the page tells the app (its parent window)
# how far it has scrolled and how big it is, and scrolls when the app forwards the mouse wheel during
# pen mode. Only numbers go out; only "scroll by" comes in, and only from the parent window.
SCROLL_REPORTER = b"""<script>(function(){try{
var de=document.documentElement,b=document.body;
function size(){return{w:Math.max(de.scrollWidth,b?b.scrollWidth:0),h:Math.max(de.scrollHeight,b?b.scrollHeight:0)};}
function send(){var s=size();parent.postMessage({readhold:"scroll",x:window.scrollX,y:window.scrollY,w:s.w,h:s.h,vw:de.clientWidth,vh:de.clientHeight},"*");}
addEventListener("scroll",send,{passive:true});addEventListener("resize",send);addEventListener("load",send);
addEventListener("message",function(e){if(e.source!==parent||!e.data||e.data.readhold!=="scroll-by")return;
var dx=+e.data.dx||0,dy=+e.data.dy||0;if(isFinite(dx)&&isFinite(dy))window.scrollBy(dx,dy);});
if(window.ResizeObserver&&b)new ResizeObserver(send).observe(b);send();
}catch(e){}})();</script>"""


def with_scroll_reporter(html: bytes) -> bytes:
    """Insert SCROLL_REPORTER before the last </body> (or at the end if there is none)."""
    low = html.lower()
    at = low.rfind(b"</body>")
    return html + SCROLL_REPORTER if at < 0 else html[:at] + SCROLL_REPORTER + html[at:]


def lecture_dir(lecture_id: str) -> Path:
    d = config.library_dir() / "lectures" / lecture_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise HTTPException(404, "not found")
    return value


# ------------------------------------------------------------------ parsing
def _parse_pdf(path: Path) -> list[dict]:
    import pypdfium2 as pdfium

    from .importers.pdf_import import PDFIUM_LOCK

    pages = []
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception as e:  # noqa: BLE001
            raise ImportFailed(f"Could not open the PDF: {e}") from e
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                try:
                    tp = page.get_textpage()
                    text = tp.get_text_range().replace("\r\n", "\n")
                    tp.close()
                    first = next((ln.strip() for ln in text.split("\n") if len(ln.strip()) > 2), "")
                    pages.append({"title": first[:120], "text": text[:20000], "width": page.get_width(), "height": page.get_height()})
                finally:
                    page.close()
        finally:
            pdf.close()
    if not pages:
        raise ImportFailed("The PDF has no pages.")
    return pages


def _check_zip(data: bytes) -> None:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ImportFailed("This .pptx isn't a valid PowerPoint file.") from e
    infos = z.infolist()
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_ZIP_TOTAL:
        raise ImportFailed("This PowerPoint file expands to something far too large to open safely.")
    if "ppt/presentation.xml" not in z.namelist():
        raise ImportFailed("This zip file isn't a PowerPoint deck.")


def _rgb(color: Any) -> str | None:
    try:
        if color is not None and color.type is not None and color.rgb is not None:
            return f"#{color.rgb}"
    except Exception:  # noqa: BLE001 — theme colours have no rgb
        return None
    return None


def _fill(shape: Any) -> str | None:
    try:
        if shape.fill.type == 1:  # MSO_FILL.SOLID
            return _rgb(shape.fill.fore_color)
    except Exception:  # noqa: BLE001
        return None
    return None


def _pct(v: int | None, total: int) -> float:
    return round(100 * (v or 0) / total, 3) if total else 0.0


def _parse_pptx(data: bytes, lid: str) -> list[dict]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

    _check_zip(data)
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise ImportFailed(f"Could not open the PowerPoint file: {e.__class__.__name__}") from e
    sw, sh = int(prs.slide_width or 9144000), int(prs.slide_height or 6858000)
    out_dir = lecture_dir(lid)
    pages: list[dict] = []

    def box(shape: Any) -> dict:
        return {"x": _pct(shape.left, sw), "y": _pct(shape.top, sh), "w": _pct(shape.width, sw), "h": _pct(shape.height, sh)}

    def is_title(shape: Any) -> bool:
        try:
            return shape.is_placeholder and shape.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
        except Exception:  # noqa: BLE001
            return False

    def text_el(shape: Any) -> dict | None:
        paras = []
        default = 36 if is_title(shape) else 18
        for p in shape.text_frame.paragraphs:
            runs = []
            for r in p.runs:
                if not r.text:
                    continue
                f = r.font
                runs.append({
                    "t": r.text[:4000],
                    "b": bool(f.bold), "i": bool(f.italic),
                    "size": round(f.size.pt, 1) if f.size else None,
                    "color": _rgb(f.color) if f.color and f.color.type is not None else None,
                })
            level = int(p.level or 0)
            align = {1: "left", 2: "center", 3: "right", 4: "justify"}.get(int(p.alignment) if p.alignment is not None else 0, "")
            paras.append({"level": level, "align": align, "runs": runs, "default": max(10, default - 2 * level)})
        if not any(p["runs"] for p in paras):
            return None
        return {"type": "text", **box(shape), "title": is_title(shape), "paras": paras, "fill": _fill(shape)}

    def walk(shapes: Any, els: list[dict]) -> None:
        for shape in shapes:
            try:
                st = shape.shape_type
                if st == MSO_SHAPE_TYPE.GROUP:
                    walk(shape.shapes, els)
                    continue
                if st == MSO_SHAPE_TYPE.PICTURE or getattr(shape, "image", None) is not None and st != MSO_SHAPE_TYPE.PLACEHOLDER:
                    img = shape.image
                    ext = RASTER.get((img.ext or "").lower())
                    if not ext:
                        continue  # EMF/WMF/SVG: not shown, never served
                    blob = img.blob
                    name = f"img-{hashlib.sha256(blob).hexdigest()[:16]}.{img.ext.lower()}"
                    target = out_dir / name
                    if not target.exists():
                        target.write_bytes(blob)
                    els.append({"type": "image", **box(shape), "src": name})
                elif getattr(shape, "has_table", False) and shape.has_table:
                    rows = [[c.text[:500] for c in row.cells] for row in shape.table.rows]
                    els.append({"type": "table", **box(shape), "rows": rows[:60]})
                elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                    el = text_el(shape)
                    if el:
                        els.append(el)
                    elif _fill(shape):
                        els.append({"type": "box", **box(shape), "fill": _fill(shape)})
                elif _fill(shape):
                    els.append({"type": "box", **box(shape), "fill": _fill(shape)})
            except Exception:  # noqa: BLE001 — one odd shape must never sink the deck
                log.warning("Skipped a PowerPoint shape on slide %d", len(pages) + 1, exc_info=True)

    for slide in prs.slides:
        els: list[dict] = []
        walk(slide.shapes, els)
        bg = None
        try:
            if slide.background.fill.type == 1:
                bg = _rgb(slide.background.fill.fore_color)
        except Exception:  # noqa: BLE001
            bg = None
        title = ""
        try:
            if slide.shapes.title is not None:
                title = slide.shapes.title.text_frame.text.strip()
        except Exception:  # noqa: BLE001
            title = ""
        text = "\n".join("".join(r["t"] for r in p["runs"]) for e in els if e["type"] == "text" for p in e["paras"])
        notes = ""
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                notes = slide.notes_slide.notes_text_frame.text.strip()
        except Exception:  # noqa: BLE001
            notes = ""
        pages.append({
            "title": (title or next((ln for ln in text.split("\n") if ln.strip()), ""))[:120],
            "text": text[:20000], "speaker_notes": notes[:20000],
            "width": sw / EMU_PER_PT, "height": sh / EMU_PER_PT,
            "layout": json.dumps({"bg": bg, "els": els}, ensure_ascii=False),
        })
    if not pages:
        raise ImportFailed("The deck has no slides.")
    return pages


def _parse_html(data: bytes, stem: str) -> tuple[str, list[dict]]:
    from lxml import html as lxml_html

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    title = stem
    plain = ""
    try:
        tree = lxml_html.fromstring(text or "<p></p>")
        t = tree.findtext(".//title")
        if t and t.strip():
            title = t.strip()[:200]
        for bad in tree.xpath("//script|//style|//noscript"):
            bad.drop_tree()
        plain = re.sub(r"\s+", " ", tree.text_content()).strip()
    except Exception:  # noqa: BLE001 — unparseable HTML still opens in the sandbox
        plain = ""
    return title, [{"title": title, "text": plain[:50000], "width": 0, "height": 0}]


def import_lecture(db: DB, filename: str, data: bytes) -> dict:
    ext = Path(filename).suffix.lower()
    kind = KINDS.get(ext)
    stem = Path(filename).stem.replace("_", " ").strip() or "Lecture"
    if not kind:
        raise ImportFailed("Lectures can be PDF, PowerPoint (.pptx) or HTML files.")
    if not data:
        raise ImportFailed("The file is empty.")
    if kind == "pdf" and not data.lstrip()[:5].startswith(b"%PDF"):
        raise ImportFailed("This file is named .pdf but isn't a PDF.")
    if kind == "pptx" and not data.startswith(b"PK"):
        raise ImportFailed("This file is named .pptx but isn't a PowerPoint deck. (Old .ppt files: save as .pptx first.)")
    lid = new_id()
    digest = keep_original(data, ".html" if kind == "html" else ext)
    title = stem
    if kind == "pdf":
        pages = _parse_pdf(config.library_dir() / f"{digest}{ext}")
    elif kind == "pptx":
        pages = _parse_pptx(data, lid)
    else:
        title, pages = _parse_html(data, stem)
    t = now()
    with db.transaction():
        db.conn.execute(
            "INSERT INTO lectures (id, title, kind, source, file_hash, pages, device_id, created_at, updated_at, deleted)"
            " VALUES (?,?,?,?,?,?,?,?,?,0)",
            (lid, title[:300], kind, filename[:300], digest, len(pages), db.device, t, t),
        )
        db.conn.executemany(
            "INSERT INTO lecture_pages (id, lecture_id, ord, title, text, speaker_notes, width, height, layout, device_id,"
            " created_at, updated_at, deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
            [(new_id(), lid, i, p.get("title", ""), p.get("text", ""), p.get("speaker_notes", ""), p.get("width", 0),
              p.get("height", 0), p.get("layout", ""), db.device, t, t) for i, p in enumerate(pages)],
        )
    return {"id": lid, "title": title, "kind": kind, "pages": len(pages)}


MAX_RENDER_PX = 20_000  # the tallest picture of a page, in pixels (a 1 x 14,400 pt page would ask for millions)


def render_pdf_page(lecture: dict, page: int, width: int) -> Path:
    """PNG of one PDF page at (about) the requested width, cached next to the lecture."""
    import pypdfium2 as pdfium

    from .importers.pdf_import import PDFIUM_LOCK

    width = next((w for w in RENDER_WIDTHS if w >= width), RENDER_WIDTHS[-1])
    out = lecture_dir(lecture["id"]) / f"p{page}-w{width}.png"
    if out.exists():
        return out
    src = config.library_dir() / f"{lecture['file_hash']}.pdf"
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(src))
        try:
            pg = pdf[page]
            try:
                scale = width / max(pg.get_width(), 1)
                scale = min(scale, MAX_RENDER_PX / max(pg.get_height(), 1))  # a page drawn very tall stays a sane size
                bitmap = pg.render(scale=scale)
                img = bitmap.to_pil()
                bitmap.close()
            finally:
                pg.close()
        finally:
            pdf.close()
    tmp = out.with_name(f"{out.stem}-{new_id()}.tmp")  # unique: two renders of one page never share a temp file
    img.save(tmp, "PNG", optimize=False)
    tmp.replace(out)  # atomic: a half-written file is never served
    return out


# ------------------------------------------------------------------ request bodies
NoteKind = Literal["text", "cornell", "snip", "question", "sketch", "recall"]


class LecturePatch(Body):
    title: str | None = Field(None, min_length=1, max_length=300)
    position: int | None = Field(None, ge=0)
    page_tint: Literal["normal", "dim", "sepia", "night"] | None = None


# Sticky-note colours for typed notes (names, not CSS: the front end maps them to colours).
NOTE_COLOR = r"^(|sun|mint|sky|lilac|peach|rose)$"
Paper = Literal["lined", "dotted", "grid", "plain"]
NOTEBOOK_W, NOTEBOOK_H = 850, 1100  # page shape of a blank notebook (like a sheet of letter paper)
MAX_NOTEBOOK_PAGES = 500


class NoteIn(BaseModel):
    page: int | None = Field(None, ge=0)
    kind: NoteKind
    body: str = Field("", max_length=50000)
    data: dict = Field(default_factory=dict)
    color: str = Field("", pattern=NOTE_COLOR)


class NotePatch(BaseModel):
    body: str | None = Field(None, max_length=50000)
    data: dict | None = None
    color: str | None = Field(None, pattern=NOTE_COLOR)
    page: int | None = Field(None, ge=0)


class NotebookIn(Body):
    title: str = Field("My notes", min_length=1, max_length=300)
    paper: Paper = "lined"


class PagePatch(BaseModel):
    text: str | None = Field(None, max_length=100_000)
    paper: Paper | None = None


def create_notebook(db: DB, title: str, paper: str) -> dict:
    """A notebook is a lecture with no file: blank pages you write and draw on, with the same notebook beside them."""
    lid, t = new_id(), now()
    with db.transaction():
        db.conn.execute(
            "INSERT INTO lectures (id, title, kind, source, file_hash, pages, device_id, created_at, updated_at, deleted)"
            " VALUES (?,?,?,?,?,?,?,?,?,0)",
            (lid, title.strip()[:300] or "My notes", "notebook", "", "", 1, db.device, t, t),
        )
        _insert_blank_page(db, lid, 0, paper, t)
    return {"id": lid, "title": title, "kind": "notebook", "pages": 1}


def _insert_blank_page(db: DB, lid: str, ord_: int, paper: str, t: str) -> None:
    db.conn.execute(
        "INSERT INTO lecture_pages (id, lecture_id, ord, title, text, speaker_notes, width, height, layout, device_id,"
        " created_at, updated_at, deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (new_id(), lid, ord_, "", "", "", NOTEBOOK_W, NOTEBOOK_H, json.dumps({"paper": paper}), db.device, t, t),
    )


class InkIn(BaseModel):
    strokes: list = Field(default_factory=list, max_length=5000)


MAX_INK_BYTES = 3 * 1024 * 1024
INK_OWNERS = {"lecture_page", "note", "journal"}


def _clean_strokes(strokes: list) -> list:
    """Keep only well-formed strokes: {tool, color, size, points:[[x, y, pressure], ...]} with numbers in range."""
    clean = []
    for s in strokes:
        if not isinstance(s, dict) or not isinstance(s.get("points"), list):
            continue
        tool = s.get("tool") if s.get("tool") in ("pen", "highlighter") else "pen"
        color = s.get("color") if isinstance(s.get("color"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", s.get("color", "")) else "#222222"
        size = s.get("size") if isinstance(s.get("size"), (int, float)) and 0.0005 <= s["size"] <= 0.1 else 0.004
        pts = []
        for p in s["points"][:20000]:
            if isinstance(p, list) and len(p) >= 2 and all(isinstance(v, (int, float)) for v in p[:3]):
                x, y = float(p[0]), float(p[1])
                pr = float(p[2]) if len(p) > 2 else 0.5
                if -0.1 <= x <= 1.1 and -0.1 <= y <= 3.0:
                    pts.append([round(x, 5), round(y, 5), round(min(max(pr, 0.0), 1.0), 3)])
        if pts:
            clean.append({"tool": tool, "color": color, "size": size, "points": pts})
    return clean


def _note_out(n: dict) -> dict:
    try:
        n["data"] = json.loads(n["data"] or "{}")
    except ValueError:
        n["data"] = {}
    return n


# ------------------------------------------------------------------ routes
def register(app: FastAPI, db: DB) -> None:
    from . import services
    from starlette.concurrency import run_in_threadpool

    def lecture(lid: str) -> dict:
        return need_row(db, "lectures", _check_id(lid))

    def sync_question_card(note: dict) -> None:
        """A question note is also a review card (front: the question, back: your answer)."""
        data = note["data"] if isinstance(note["data"], dict) else json.loads(note["data"] or "{}")
        front, back = note["body"].strip(), str(data.get("back", "")).strip()
        if note["kind"] == "question" and front and back and not note.get("deleted"):
            services.upsert_card(db, "lecture_note", note["id"], front, back, None)
        else:
            services.remove_card(db, "lecture_note", note["id"])

    @app.get("/api/lectures")
    def api_lectures():
        return db.all(
            "SELECT l.id, l.title, l.kind, l.pages, l.position, l.updated_at,"
            " (SELECT COUNT(*) FROM lecture_notes n WHERE n.lecture_id=l.id AND n.deleted=0) AS notes"
            " FROM lectures l WHERE l.deleted=0 ORDER BY l.updated_at DESC"
        )

    @app.post("/api/lectures/import")
    async def api_lecture_import(file: UploadFile = File(...)):
        data = await file.read(config.MAX_FILE_BYTES + 1)
        if len(data) > config.MAX_FILE_BYTES:
            raise HTTPException(413, "The file is larger than 50 MB.")
        try:
            return await run_in_threadpool(import_lecture, db, file.filename or "lecture", data)
        except ImportFailed as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/api/lectures/notebook")
    def api_notebook_create(body: NotebookIn):
        return create_notebook(db, body.title, body.paper)

    @app.get("/api/lectures/{lid}")
    def api_lecture(lid: str):
        lec = lecture(lid)
        pages = db.all(
            "SELECT ord, title, speaker_notes, width, height, layout, text FROM lecture_pages WHERE lecture_id=? AND deleted=0 ORDER BY ord",
            (lid,),
        )
        for p in pages:
            p["layout"] = json.loads(p["layout"]) if p["layout"] else None
            if lec["kind"] != "notebook":
                p.pop("text")  # imported pages keep their text for search only; a notebook page's text is your writing
        return {**lec, "page_list": pages}

    def notebook_page(lid: str, ord_: int) -> tuple[dict, dict]:
        lec = lecture(lid)
        if lec["kind"] != "notebook":
            raise HTTPException(404, "not found")
        row = db.one("SELECT * FROM lecture_pages WHERE lecture_id=? AND ord=? AND deleted=0", (lid, ord_))
        if not row:
            raise HTTPException(404, "No such page.")
        return lec, row

    @app.post("/api/lectures/{lid}/pages")
    def api_notebook_add_page(lid: str):
        """A fresh page at the end of a notebook, on the same paper as the last one."""
        lec = lecture(lid)
        if lec["kind"] != "notebook":
            raise HTTPException(404, "not found")
        if lec["pages"] >= MAX_NOTEBOOK_PAGES:
            raise HTTPException(422, f"A notebook holds up to {MAX_NOTEBOOK_PAGES} pages. Start a new notebook.")
        last = db.one("SELECT layout FROM lecture_pages WHERE lecture_id=? AND deleted=0 ORDER BY ord DESC LIMIT 1", (lid,))
        try:
            paper = json.loads(last["layout"]).get("paper", "lined") if last else "lined"
        except (ValueError, AttributeError):
            paper = "lined"
        t = now()
        with db.transaction():
            _insert_blank_page(db, lid, lec["pages"], paper if paper in ("lined", "dotted", "grid", "plain") else "lined", t)
            db.conn.execute("UPDATE lectures SET pages=?, position=?, updated_at=?, device_id=? WHERE id=?", (lec["pages"] + 1, lec["pages"], t, db.device, lid))
        return {"ord": lec["pages"], "title": "", "speaker_notes": "", "width": NOTEBOOK_W, "height": NOTEBOOK_H,
                "layout": {"paper": paper}, "text": ""}

    @app.patch("/api/lectures/{lid}/pages/{ord_}")
    def api_notebook_page_patch(lid: str, ord_: int, body: PagePatch):
        """Your writing on a notebook page (saved as you type), or the page's paper."""
        _, row = notebook_page(lid, ord_)
        fields: dict = {}
        if body.text is not None:
            fields["text"] = body.text
        if body.paper is not None:
            fields["layout"] = json.dumps({"paper": body.paper})
        if fields:
            db.update("lecture_pages", row["id"], fields)
            db.execute("UPDATE lectures SET updated_at=?, device_id=? WHERE id=?", (now(), db.device, lid))
        return {"ok": True}

    @app.patch("/api/lectures/{lid}")
    def api_lecture_patch(lid: str, body: LecturePatch):
        lec = lecture(lid)
        fields = body.model_dump(exclude_none=True)
        if "position" in fields:
            fields["position"] = min(fields["position"], max(lec["pages"] - 1, 0))
        db.update("lectures", lid, fields)
        return lecture(lid)

    @app.delete("/api/lectures/{lid}")
    def api_lecture_delete(lid: str):
        lecture(lid)
        db.soft_delete("lectures", lid)
        return {"ok": True}

    @app.post("/api/lectures/{lid}/restore")
    def api_lecture_restore(lid: str):
        if not db.one("SELECT 1 FROM lectures WHERE id=?", (_check_id(lid),)):
            raise HTTPException(404, "not found")
        db.update("lectures", lid, {"deleted": 0})
        return lecture(lid)

    @app.get("/api/lectures/{lid}/pages/{page}/image")
    def api_lecture_page_image(lid: str, page: int, w: int = 1400):
        lec = lecture(lid)
        if lec["kind"] != "pdf" or not 0 <= page < lec["pages"]:
            raise HTTPException(404, "not found")
        path = render_pdf_page(lec, page, max(200, min(w, 4000)))
        return FileResponse(path, media_type="image/png")

    @app.get("/api/lectures/{lid}/assets/{name}")
    def api_lecture_asset(lid: str, name: str):
        lecture(lid)
        m = re.fullmatch(r"img-[0-9a-f]{16}\.(png|jpe?g|gif|bmp)", name)
        if not m:
            raise HTTPException(404, "not found")
        path = config.library_dir() / "lectures" / lid / name
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type=f"image/{RASTER[m.group(1)]}")

    @app.get("/api/lectures/{lid}/content.html")
    def api_lecture_html(lid: str):
        """The HTML lecture itself, for the sandboxed iframe. The middleware gives it SANDBOX_CSP."""
        lec = lecture(lid)
        if lec["kind"] != "html":
            raise HTTPException(404, "not found")
        path = config.library_dir() / f"{lec['file_hash']}.html"
        if not path.is_file():
            raise HTTPException(404, "The original file is missing from the library.")
        return Response(with_scroll_reporter(path.read_bytes()), media_type="text/html; charset=utf-8")

    # ---- notebook
    @app.get("/api/lectures/{lid}/notes")
    def api_notes(lid: str):
        lecture(lid)
        return [_note_out(n) for n in db.all(
            "SELECT * FROM lecture_notes WHERE lecture_id=? AND deleted=0 ORDER BY page IS NULL, page, created_at", (lid,)
        )]

    @app.post("/api/lectures/{lid}/notes")
    def api_note_create(lid: str, body: NoteIn):
        lec = lecture(lid)
        if body.page is not None and body.page >= lec["pages"]:
            raise HTTPException(422, "No such page.")
        payload = json.dumps(body.data, ensure_ascii=False)
        if len(payload) > 200_000:
            raise HTTPException(413, "That note is too large.")
        note = db.insert("lecture_notes", {"lecture_id": lid, "page": body.page, "kind": body.kind, "body": body.body,
                                           "data": payload, "color": body.color})
        note = _note_out(note)
        sync_question_card(note)
        db.update("lectures", lid, {"position": lec["position"]})  # bumps updated_at: recently used lectures first
        return note

    @app.patch("/api/lecture-notes/{nid}")
    def api_note_patch(nid: str, body: NotePatch):
        note = need_row(db, "lecture_notes", _check_id(nid))
        fields = body.model_dump(exclude_none=True)
        if "page" in fields:
            pages = db.scalar("SELECT pages FROM lectures WHERE id=?", (note["lecture_id"],)) or 0
            if fields["page"] >= pages:
                raise HTTPException(422, "No such page.")
        if "data" in fields:
            fields["data"] = json.dumps(fields["data"], ensure_ascii=False)
            if len(fields["data"]) > 200_000:
                raise HTTPException(413, "That note is too large.")
        db.update("lecture_notes", nid, fields)
        fresh = _note_out(need_row(db, "lecture_notes", nid))
        sync_question_card(fresh)
        return fresh

    @app.delete("/api/lecture-notes/{nid}")
    def api_note_delete(nid: str):
        note = need_row(db, "lecture_notes", _check_id(nid))
        db.soft_delete("lecture_notes", nid)
        services.remove_card(db, "lecture_note", nid)
        db.soft_delete("ink", db.scalar("SELECT id FROM ink WHERE owner_type='note' AND owner_id=?", (nid,)) or "")
        return {"ok": True, "lecture_id": note["lecture_id"]}

    @app.get("/api/lectures/{lid}/export")
    def api_lecture_export(lid: str):
        """The notebook as Markdown (text, Cornell sheet, questions, snips and recalls with page numbers)."""
        lec = lecture(lid)
        from .text import math_to_markdown

        notes = [_note_out(n) for n in db.all(
            "SELECT * FROM lecture_notes WHERE lecture_id=? AND deleted=0 ORDER BY page IS NULL DESC, page, created_at", (lid,)
        )]
        out = [f"# {lec['title']}", ""]
        if lec["kind"] == "notebook":
            for p in db.all("SELECT ord, text FROM lecture_pages WHERE lecture_id=? AND deleted=0 ORDER BY ord", (lid,)):
                if p["text"].strip():
                    out += [f"## Page {p['ord'] + 1}", "", p["text"].strip(), ""]
            if notes:
                out += ["## Notebook", ""]
        for n in notes:
            where = "Whole lecture" if n["page"] is None else f"Page {n['page'] + 1}"
            d = n["data"]
            if n["kind"] == "cornell":
                out += ["## Cornell sheet", "", "**Cues**", "", d.get("cues", ""), "", "**Notes**", "", d.get("notes", ""), "",
                        "**Summary**", "", d.get("summary", ""), ""]
            elif n["kind"] == "question":
                out += [f"- **Q ({where}):** {n['body']}", f"  - {d.get('back', '')}"]
            elif n["kind"] == "snip":
                out += [f"- ✂ Snip ({where}): {n['body']}"]
            elif n["kind"] == "recall":
                out += [f"- Recall ({where}): {n['body']}"]
            elif n["kind"] == "sketch":
                out += [f"- ✎ Sketch ({where}){': ' + n['body'] if n['body'] else ''}"]
            else:
                out += [f"- {where}: {n['body']}"]
        return {"markdown": math_to_markdown("\n".join(out).strip() + "\n")}

    # ---- digital ink
    @app.get("/api/ink/{owner_type}/{owner_id}")
    def api_ink_get(owner_type: str, owner_id: str):
        if owner_type not in INK_OWNERS or not re.fullmatch(r"[0-9a-f]{32}(:\d{1,5})?|\d{4}-\d{2}-\d{2}", owner_id):
            raise HTTPException(404, "not found")
        row = db.one("SELECT strokes, updated_at FROM ink WHERE owner_type=? AND owner_id=? AND deleted=0", (owner_type, owner_id))
        return {"strokes": json.loads(row["strokes"]) if row else [], "updated_at": row["updated_at"] if row else None}

    @app.put("/api/ink/{owner_type}/{owner_id}")
    def api_ink_put(owner_type: str, owner_id: str, body: InkIn):
        if owner_type not in INK_OWNERS or not re.fullmatch(r"[0-9a-f]{32}(:\d{1,5})?|\d{4}-\d{2}-\d{2}", owner_id):
            raise HTTPException(404, "not found")
        strokes = _clean_strokes(body.strokes)
        payload = json.dumps(strokes, separators=(",", ":"))
        if len(payload) > MAX_INK_BYTES:
            raise HTTPException(413, "This page has too much ink to save. Start a new sketch.")
        row = db.one("SELECT id FROM ink WHERE owner_type=? AND owner_id=?", (owner_type, owner_id))
        if row:
            db.update("ink", row["id"], {"strokes": payload, "deleted": 0})
        else:
            db.insert("ink", {"owner_type": owner_type, "owner_id": owner_id, "strokes": payload})
        return {"ok": True, "strokes": len(strokes)}
