"""Local FastAPI server: 127.0.0.1 only, session token, Host check, strict CSP."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import secrets
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bodies import Body
from . import ai, compass, config, growth, hub, journal, lectures, organize, pages, passages, planner, readplan, redact, related, search, services, store, think, tidy, timer, trash
from .db import DB, now
from .importers import ImportFailed, import_bytes, import_text
from .store import doc_sentences, load_document
from .terms import find_acronyms, find_definitions

log = logging.getLogger(__name__)

COOKIE = "readhold_session"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; frame-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "wpm": 250,
    "comfort_wpm": 250,
    "pacer_mode": "sentence",  # sentence | word | focus
    "energy": "medium",
    "theme": "clean",  # the default theme; Sand was the default until 2026-11-27
    "intensity": "gentle",  # off | still | gentle | lively (reduce-motion always means still)
    "glass": "balanced",  # solid | balanced | clear: how much of the theme shows through the panels
    "sound": False,  # ambient sound is always off until turned on
    "sound_volume": 0.35,
    "journal_blur": False,  # blur journal text until you point at it
    "notebook_width": 0,  # lecture notebook width in px; 0 = automatic
    "note_scale": 1.0,  # lecture notebook text size
    "timer_sound": True,  # a soft chime when a timer ends
    "timer_rhythm": False,  # offer a short break after each focus run
    "dark": "auto",  # auto | light | dark
    "font": "atkinson",
    "font_size": 20,
    "line_width": 66,
    "line_height": 1.7,
    "tts_voice": "",
    "tts_rate": 1.0,
    "review_cap": 30,
    "simple_mode": False,  # fewer cards on the Overview and a shorter menu
    "reader_panels_hidden": False,  # the reader's map and side panel folded away, so the page sits alone over the theme; Ctrl+\ or Show panels brings them back
    "nav_hidden": False,  # the side menu hidden, so the page (Study, a lecture, a note) has the whole window; Ctrl+\ or Menu brings it back
    "prediction_prompts": True,
    "skip_background": True,
    "clean_view": True,
    "speed_ramp": True,
    "comfort_by_type": {},
    # the AI assistant (docs/ai/PLAN.md). Off until switched on; `ai_mode: off` is the one switch that stops all of it.
    # An API key is never a setting: it lives in the operating system's credential store (readhold/ai/keys.py).
    "ai_mode": "off",  # off | local | cloud
    "ai_local_api": "ollama",  # ollama | openai (an OpenAI-compatible server: llama.cpp, LM Studio)
    "ai_local_endpoint": "http://localhost:11434",
    "ai_local_model": "",
    "ai_local_small_model": "",  # for the short tasks; empty = the model above
    "ai_cloud_provider": "anthropic",  # anthropic | openai
    "ai_cloud_model": "",  # empty = the provider's default
    "ai_cloud_small_model": "",
    "ai_timeout_s": 60,
    "ai_budget_local": 2_000_000,  # tokens a day per provider; 0 = no limit
    "ai_budget_cloud": 200_000,
    "ai_preview": False,  # milestone 4.4: show what will be sent before a cloud call
    "ai_log_days": 30,  # milestone 4.4: how long the AI log keeps its lines (1, 7 or 30)
    "ai_cloud_only_tagged": False,  # milestone 4.4: cloud mode sends only what is tagged #cloud
    "plan_minutes_a_day": 120,  # milestone 5.3: the time you have for tasks each day, as the Plan chat last used it
}
assert all(DEFAULT_SETTINGS[k] == v for k, v in ai.settings.DEFAULTS.items())  # one list, written twice on purpose

HL_TYPES = Literal["claim", "evidence", "definition", "confusing", "idea"]


# ------------------------------------------------------------------ request bodies
class TextIn(BaseModel):
    title: str = ""
    text: str = Field(max_length=5_000_000)
    format: Literal["markdown", "text"] = "markdown"
    why: str = ""


class DocPatch(BaseModel):
    title: str | None = None
    why: str | None = None
    deadline: str | None = None
    status: Literal["queued", "reading", "finished"] | None = None
    current_pass: int | None = Field(None, ge=1, le=3)
    explain_text: str | None = None
    quest_question_id: str | None = None  # "" unlinks
    critique: str | None = Field(None, max_length=20000)
    reproduce: str | None = Field(None, max_length=2000)


class PositionIn(BaseModel):
    position: int = Field(ge=0)


class ReadIn(BaseModel):
    ords: list[int] = Field(max_length=5000)


class SlowIn(BaseModel):
    ord: int
    signal: float = Field(ge=-1, le=1)


class SectionPatch(BaseModel):
    title: str | None = None
    kind: str | None = None
    background: bool | None = None
    hidden: bool | None = None
    prediction: str | None = None
    prediction_check: str | None = None


class SplitIn(BaseModel):
    title: str = "New section"


class QuestionIn(Body):
    document_id: str
    text: str = Field(min_length=1, max_length=500)
    section_id: str | None = None
    source_sentence: int | None = None
    section_kind: str | None = None


class QuestionPatch(BaseModel):
    text: str | None = None
    answer: str | None = None


class LinkIn(BaseModel):
    paragraph_id: str


class HighlightIn(BaseModel):
    document_id: str
    sentence: int
    end_sentence: int | None = None
    type: HL_TYPES
    note: str = ""


class HighlightPatch(BaseModel):
    note: str | None = None
    cloze: str | None = None
    resolved: bool | None = None
    type: HL_TYPES | None = None


class NoteIn(Body):
    document_id: str
    sentence: int
    text: str = Field(min_length=1, max_length=5000)


class NotePatch(BaseModel):
    text: str


class TermIn(Body):
    term: str = Field(min_length=1, max_length=200)
    guess: str = ""
    definition: str = ""
    document_id: str | None = None
    sentence: int | None = None
    source_text: str = ""


class TermPatch(BaseModel):
    guess: str | None = None
    definition: str | None = None
    is_concept: bool | None = None


class RatingIn(BaseModel):
    rating: int = Field(ge=1, le=4)


class IdeaIn(Body):
    text: str = Field(min_length=1, max_length=5000)
    document_id: str | None = None
    sentence: int | None = None


class SessionIn(BaseModel):
    document_id: str | None = None
    energy: Literal["low", "medium", "high"] = "medium"
    time_box_min: int = Field(15, ge=1, le=240)
    question: str = ""
    quest_id: str | None = None  # the session works on the main quest (reading for it, or a focus step)
    step_id: str | None = None


class SessionPatch(BaseModel):
    focused_ms: int | None = None
    longest_run_ms: int | None = None
    distractions: int | None = None
    sentences_read: int | None = None
    next_step: str | None = None
    output: str | None = Field(None, max_length=5000)  # what the session produced
    time_box_min: int | None = Field(None, ge=1, le=240)
    feel: Literal["energized", "neutral", "drained", ""] | None = None
    ended: bool = False


# ------------------------------------------------------------------ app factory
NO_TELEMETRY = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}


def create_app(db: DB, token: str, allowed_hosts: set[str]) -> FastAPI:
    # No telemetry, ever: FastAPI's OpenTelemetry hooks (since 0.15x) are all switched off, so nothing is recorded,
    # and export can never be configured from the environment (tests/test_no_network.py checks it)
    app = FastAPI(title="Readhold", docs_url=None, redoc_url=None, openapi_url=None, telemetry=NO_TELEMETRY)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        def refuse(status: int, detail: str) -> JSONResponse:
            r = JSONResponse({"detail": detail}, status_code=status)
            r.headers["Content-Security-Policy"] = CSP
            r.headers["X-Content-Type-Options"] = "nosniff"
            r.headers["Referrer-Policy"] = "no-referrer"
            r.headers["Cache-Control"] = "no-store"
            return r

        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return refuse(403, "bad host")
        path = request.url.path
        if path != "/auth":
            supplied = request.cookies.get(COOKIE) or request.headers.get("x-readhold-token", "")
            if not secrets.compare_digest(supplied.encode(), token.encode()):
                return refuse(401, "missing session token")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # a write must come from this page itself. Another page on this computer (another port is the "same site",
            # so the browser sends the cookie) gets refused: by its Origin, or by the browser's own Sec-Fetch-Site.
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site")
            if (origin is not None and origin != f"{request.url.scheme}://{host}") or (fetch_site is not None and fetch_site not in ("same-origin", "none")):
                return refuse(403, "a write from another page")
        ai.privacy.approve(request.headers.get("x-ai-approve"))  # a one-time approval of a send preview, for this request only
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            log.exception("Unhandled error on %s", path)
            response = JSONResponse({"detail": "Internal error (see data/logs/readhold.log)"}, status_code=500)
        # HTML lectures run in a sandboxed iframe under their own no-network policy; everything else gets the strict one
        sandboxed = path.startswith("/api/lectures/") and path.endswith("/content.html")
        response.headers["Content-Security-Policy"] = lectures.SANDBOX_CSP if sandboxed else CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Cache-Control", "no-store")
        # for this page only: no other page may open it, embed what it serves, or use a camera or microphone through it
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, e: RequestValidationError):
        """A refused request says what was wrong and where, never what was sent (it may hold a key or a document)."""
        return JSONResponse({"detail": [{k: v for k, v in err.items() if k in ("type", "loc", "msg")} for err in e.errors()]}, status_code=422)

    @app.exception_handler(ai.privacy.PreviewNeeded)
    async def preview_needed(request: Request, e: ai.privacy.PreviewNeeded):
        """Nothing was sent: the page shows this text, and sends the same request again if you approve it."""
        return JSONResponse({"detail": "Approve what will be sent off this computer.", "preview": e.view()}, status_code=428)

    @app.get("/auth")
    def auth(request: Request):
        supplied = request.query_params.get("token", "")
        if not secrets.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "bad token")
        r = RedirectResponse("/", status_code=303)
        r.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
        return r

    @app.get("/")
    def index():
        return FileResponse(config.WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
    app.mount("/themes", StaticFiles(directory=config.THEMES_DIR), name="themes")

    def settings_dict() -> dict:
        out = dict(DEFAULT_SETTINGS)
        for r in db.all("SELECT key, value FROM settings"):
            try:
                out[r["key"]] = json.loads(r["value"])
            except ValueError:
                pass
        return out

    def need_doc(doc_id: str) -> dict:
        d = db.one("SELECT * FROM documents WHERE id=? AND deleted=0", (doc_id,))
        if not d:
            raise HTTPException(404, "document not found")
        return d

    def sentence_text(doc_id: str, a: int, b: int) -> str:
        rows = db.all(
            "SELECT text FROM sentences WHERE document_id=? AND ord BETWEEN ? AND ? ORDER BY ord", (doc_id, a, b)
        )
        return " ".join(r["text"] for r in rows)

    # ---------------- home, library, import
    @app.get("/api/home")
    def api_home():
        return services.home(db, settings_dict()["review_cap"])

    @app.get("/api/documents")
    def api_documents():
        return services.queue(db)

    def _import_result(fn, *args):
        try:
            result = fn(db, *args)
        except ImportFailed as e:
            raise HTTPException(422, str(e)) from e
        try:
            result["flags"] = sorted(ai.guard.flag_document(db, result["id"]))  # hidden or order-like text: the warning badge
        except Exception:  # noqa: BLE001  (the document is saved; a failed look is retried at the next start)
            log.exception("Could not look at %s for flagged text", result["id"])
            result["flags"] = []
        return result

    @app.post("/api/import/file")
    async def api_import_file(file: UploadFile = File(...), why: str = Form("")):
        data = await file.read(config.MAX_FILE_BYTES + 1)
        if len(data) > config.MAX_FILE_BYTES:
            raise HTTPException(413, "The file is larger than 50 MB.")
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(_import_result, import_bytes, file.filename or "upload", data, why)

    @app.post("/api/import/text")
    def api_import_text(body: TextIn):
        return _import_result(import_text, body.title, body.text, body.format, body.why)

    # ---------------- documents
    @app.get("/api/documents/{doc_id}")
    def api_document(doc_id: str, touch: bool = True):
        d = load_document(db, doc_id)
        if not d:
            raise HTTPException(404, "document not found")
        if touch and d["status"] == "queued":
            db.update("documents", doc_id, {"status": "reading"})
            d["status"] = "reading"
        return d

    @app.get("/api/documents/{doc_id}/assets/{name}")
    def api_doc_asset(doc_id: str, name: str):
        """A picture cut from the document (a PDF display equation). Only names the database knows are served."""
        if not re.fullmatch(r"[0-9a-f]{32}", doc_id) or not re.fullmatch(r"[0-9a-f]{32}\.png", name):
            raise HTTPException(404, "not found")
        known = db.scalar(
            "SELECT 1 FROM paragraphs WHERE document_id=? AND asset=? AND deleted=0", (doc_id, name)
        )
        path = store.assets_dir(doc_id) / name
        if not known or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.patch("/api/documents/{doc_id}")
    def api_doc_patch(doc_id: str, body: DocPatch):
        need_doc(doc_id)
        fields = body.model_dump(exclude_none=True)
        if fields.get("status") == "finished":
            fields["finished_at"] = now()
        if fields.get("quest_question_id") == "":
            fields["quest_question_id"] = None
        db.update("documents", doc_id, fields)
        return need_doc(doc_id)

    @app.delete("/api/documents/{doc_id}")
    def api_doc_delete(doc_id: str):
        need_doc(doc_id)
        db.soft_delete("documents", doc_id)  # soft: recoverable, never hard-deleted from the app
        passages.reindex(db, doc_id)  # a removed document is not found by search
        ai.results.forget_document(db, doc_id)  # and what a model wrote about it goes out of sight
        ai.digest.stop(doc_id)  # a digest that is running sends nothing more of it
        return {"ok": True}

    @app.post("/api/documents/{doc_id}/restore")
    def api_doc_restore(doc_id: str):
        if not db.one("SELECT 1 FROM documents WHERE id=?", (doc_id,)):
            raise HTTPException(404, "document not found")
        db.update("documents", doc_id, {"deleted": 0})
        passages.reindex(db, doc_id)  # found by search again
        return need_doc(doc_id)

    @app.post("/api/documents/{doc_id}/position")
    def api_position(doc_id: str, body: PositionIn):
        db.execute(
            "UPDATE documents SET position=?, updated_at=?, device_id=? WHERE id=?", (body.position, now(), db.device, doc_id)
        )
        return {"ok": True}

    @app.post("/api/documents/{doc_id}/read")
    def api_read(doc_id: str, body: ReadIn):
        if body.ords:
            t = now()
            marks = ",".join("?" for _ in body.ords)
            db.execute(
                f"UPDATE sentences SET read_at=?, updated_at=?, device_id=? WHERE document_id=? AND read_at IS NULL AND ord IN ({marks})",
                (t, t, db.device, doc_id, *body.ords),
            )
        return {"ok": True}

    @app.post("/api/documents/{doc_id}/slow")
    def api_slow(doc_id: str, body: SlowIn):
        """Learn where you personally slow down (long dwell, rewinds) or race ahead."""
        row = db.one("SELECT id, personal FROM sentences WHERE document_id=? AND ord=?", (doc_id, body.ord))
        if row:
            value = max(-0.3, min(0.6, row["personal"] * 0.6 + body.signal * 0.4))
            db.update("sentences", row["id"], {"personal": round(value, 3)})
        return {"ok": True}

    @app.get("/api/documents/{doc_id}/annotations")
    def api_annotations(doc_id: str):
        need_doc(doc_id)
        questions = db.all(
            "SELECT * FROM questions WHERE document_id=? AND deleted=0 ORDER BY ord, created_at", (doc_id,)
        )
        links = db.all(
            "SELECT l.question_id, l.paragraph_id FROM question_links l JOIN questions q ON q.id=l.question_id"
            " WHERE q.document_id=? AND l.deleted=0",
            (doc_id,),
        )
        for q in questions:
            q["paragraphs"] = [l["paragraph_id"] for l in links if l["question_id"] == q["id"]]
        return {
            "questions": questions,
            "highlights": db.all("SELECT * FROM highlights WHERE document_id=? AND deleted=0 ORDER BY sentence", (doc_id,)),
            "notes": db.all("SELECT * FROM notes WHERE document_id=? AND deleted=0 ORDER BY sentence", (doc_id,)),
            "terms": db.all("SELECT * FROM terms WHERE document_id=? AND deleted=0 ORDER BY term", (doc_id,)),
            "acronyms": find_acronyms([t for _, t in doc_sentences(db, doc_id)]),
        }

    @app.get("/api/documents/{doc_id}/define")
    def api_define(doc_id: str, term: str):
        need_doc(doc_id)
        glossary = db.all(
            "SELECT term, definition, guess, document_id FROM terms WHERE lower(term)=lower(?) AND deleted=0 AND definition!=''",
            (term.strip(),),
        )
        acr = find_acronyms([t for _, t in doc_sentences(db, doc_id)])
        return {
            "in_document": find_definitions(term, doc_sentences(db, doc_id)),
            "acronym": acr.get(term.strip()) or acr.get(term.strip().rstrip("s")),
            "glossary": glossary,
        }

    @app.get("/api/templates")
    def api_templates(kind: str = "other"):
        return services.question_templates(db, kind)

    @app.get("/api/documents/{doc_id}/summary")
    def api_summary(doc_id: str):
        need_doc(doc_id)
        return services.summary(db, doc_id)

    @app.post("/api/documents/{doc_id}/export")
    def api_export_doc(doc_id: str):
        need_doc(doc_id)
        return {"path": services.export_markdown_file(db, doc_id), "markdown": services.summary_markdown(db, doc_id)}

    # ---------------- fix the structure
    @app.patch("/api/sections/{sec_id}")
    def api_section_patch(sec_id: str, body: SectionPatch):
        fields = body.model_dump(exclude_none=True)
        for k in ("background", "hidden"):
            if k in fields:
                fields[k] = int(fields[k])
        if not db.update("sections", sec_id, fields):
            raise HTTPException(404, "section not found")
        if "title" in fields:
            passages.reindex(db, db.scalar("SELECT document_id FROM sections WHERE id=?", (sec_id,)))
        return {"ok": True}

    @app.post("/api/sections/{sec_id}/merge-up")
    def api_section_merge(sec_id: str):
        sec = db.one("SELECT * FROM sections WHERE id=? AND deleted=0", (sec_id,))
        if not sec:
            raise HTTPException(404, "section not found")
        prev = db.one(
            "SELECT id FROM sections WHERE document_id=? AND ord<? AND deleted=0 ORDER BY ord DESC LIMIT 1",
            (sec["document_id"], sec["ord"]),
        )
        if not prev:
            raise HTTPException(400, "This is the first section.")
        with db.transaction():
            db.conn.execute(
                "UPDATE paragraphs SET section_id=?, updated_at=?, device_id=? WHERE section_id=?", (prev["id"], now(), db.device, sec_id)
            )
            db.conn.execute("UPDATE sections SET deleted=1, updated_at=?, device_id=? WHERE id=?", (now(), db.device, sec_id))
        passages.reindex(db, sec["document_id"])
        return {"ok": True}

    @app.post("/api/paragraphs/{par_id}/split")
    def api_split(par_id: str, body: SplitIn):
        """Start a new section at this paragraph."""
        par = db.one("SELECT * FROM paragraphs WHERE id=?", (par_id,))
        if not par:
            raise HTTPException(404, "paragraph not found")
        sec = db.one("SELECT * FROM sections WHERE id=?", (par["section_id"],))
        from .text import section_kind

        with db.transaction():
            db.conn.execute(
                "UPDATE sections SET ord=ord+1 WHERE document_id=? AND ord>?", (sec["document_id"], sec["ord"])
            )
        kind = section_kind(body.title)
        new = db.insert(
            "sections",
            {"document_id": sec["document_id"], "ord": sec["ord"] + 1, "title": body.title, "kind": kind,
             "level": sec["level"], "background": int(kind in ("related", "appendix")), "hidden": int(kind == "references")},
        )
        db.execute(
            "UPDATE paragraphs SET section_id=?, updated_at=?, device_id=? WHERE section_id=? AND ord>=?",
            (new["id"], now(), db.device, sec["id"], par["ord"]),
        )
        passages.reindex(db, sec["document_id"])
        return {"id": new["id"]}

    # ---------------- questions
    @app.post("/api/questions")
    def api_q_create(body: QuestionIn):
        need_doc(body.document_id)
        n = db.scalar("SELECT COUNT(*) FROM questions WHERE document_id=? AND deleted=0", (body.document_id,)) or 0
        q = db.insert(
            "questions",
            {"document_id": body.document_id, "text": body.text.strip(), "section_id": body.section_id,
             "source_sentence": body.source_sentence, "ord": n},
        )
        if body.section_kind:
            services.learn_template(db, body.section_kind, body.text)
        return {**q, "paragraphs": []}

    @app.patch("/api/questions/{q_id}")
    def api_q_patch(q_id: str, body: QuestionPatch):
        q = db.one("SELECT * FROM questions WHERE id=?", (q_id,))
        if not q:
            raise HTTPException(404, "question not found")
        fields = body.model_dump(exclude_none=True)
        if "answer" in fields:
            fields["answered_at"] = now() if fields["answer"].strip() else None
        db.update("questions", q_id, fields)
        q.update(fields)
        if q["answer"].strip():
            back = q["answer"]
            if q["source_sentence"] is not None:
                src = sentence_text(q["document_id"], q["source_sentence"], q["source_sentence"])
                back += f"\n\nFrom the text: {src}" if src else ""
            services.upsert_card(db, "question", q_id, q["text"], back, q["document_id"])
        elif "answer" in fields:
            services.remove_card(db, "question", q_id)  # the answer was cleared: no card without an answer
        return q

    @app.delete("/api/questions/{q_id}")
    def api_q_delete(q_id: str):
        db.soft_delete("questions", q_id)
        services.remove_card(db, "question", q_id)
        return {"ok": True}

    @app.post("/api/questions/{q_id}/link")
    def api_q_link(q_id: str, body: LinkIn):
        """Tag a paragraph as answering this question (toggle)."""
        existing = db.one(
            "SELECT id, deleted FROM question_links WHERE question_id=? AND paragraph_id=?", (q_id, body.paragraph_id)
        )
        if existing:
            db.update("question_links", existing["id"], {"deleted": 0 if existing["deleted"] else 1})
            return {"linked": bool(existing["deleted"])}
        db.insert("question_links", {"question_id": q_id, "paragraph_id": body.paragraph_id})
        return {"linked": True}

    # ---------------- highlights and notes
    @app.post("/api/highlights")
    def api_hl_create(body: HighlightIn):
        need_doc(body.document_id)
        end = body.end_sentence if body.end_sentence is not None else body.sentence
        h = db.insert(
            "highlights",
            {"document_id": body.document_id, "sentence": body.sentence, "end_sentence": end, "type": body.type,
             "text": sentence_text(body.document_id, body.sentence, end), "note": body.note},
        )
        h = {**h, "cloze": "", "resolved": 0, "deleted": 0}
        services.sync_highlight_card(db, h)
        if body.type == "idea":
            db.insert("ideas", {"text": body.note or h["text"], "document_id": body.document_id, "sentence": body.sentence})
        return h

    @app.patch("/api/highlights/{h_id}")
    def api_hl_patch(h_id: str, body: HighlightPatch):
        fields = body.model_dump(exclude_none=True)
        if "resolved" in fields:
            fields["resolved"] = int(fields["resolved"])
        db.update("highlights", h_id, fields)
        h = db.one("SELECT * FROM highlights WHERE id=?", (h_id,))
        if not h:
            raise HTTPException(404, "highlight not found")
        services.sync_highlight_card(db, h)
        return h

    @app.delete("/api/highlights/{h_id}")
    def api_hl_delete(h_id: str):
        db.soft_delete("highlights", h_id)
        h = db.one("SELECT * FROM highlights WHERE id=?", (h_id,))
        if h:
            services.sync_highlight_card(db, h)
        return {"ok": True}

    @app.post("/api/notes")
    def api_note_create(body: NoteIn):
        return db.insert("notes", body.model_dump())

    @app.patch("/api/notes/{n_id}")
    def api_note_patch(n_id: str, body: NotePatch):
        old = db.one("SELECT text FROM notes WHERE id=?", (n_id,))
        fields = {"text": body.text}
        if old and old["text"] != body.text:
            fields["origin"] = ""  # once you change a note a model wrote, it is yours
        db.update("notes", n_id, fields)
        return {"ok": True}

    @app.delete("/api/notes/{n_id}")
    def api_note_delete(n_id: str):
        db.soft_delete("notes", n_id)
        return {"ok": True}

    # ---------------- terms / glossary
    @app.get("/api/terms")
    def api_terms():
        return db.all(
            "SELECT t.*, d.title AS document_title FROM terms t LEFT JOIN documents d ON d.id=t.document_id"
            " WHERE t.deleted=0 AND (t.is_concept=0 OR t.definition!='') ORDER BY lower(t.term)"
        )

    def _term_card(t: dict) -> None:
        definition = (t.get("definition") or "").strip()
        guess = (t.get("guess") or "").strip()
        if definition:
            back = definition
        elif guess:
            back = f"Your guess: {guess}\n\nNot checked yet. Look it up in the text and add the definition."
        else:
            services.remove_card(db, "term", t["id"])
            return
        if t.get("source_text"):
            back += f"\n\nIn context: {t['source_text']}"
        services.upsert_card(db, "term", t["id"], t["term"], back, t.get("document_id"))

    @app.post("/api/terms")
    def api_term_create(body: TermIn):
        t = db.insert("terms", body.model_dump())
        t["is_concept"] = 0
        _term_card(t)
        return t

    @app.patch("/api/terms/{t_id}")
    def api_term_patch(t_id: str, body: TermPatch):
        fields = body.model_dump(exclude_none=True)
        if "is_concept" in fields:
            fields["is_concept"] = int(fields["is_concept"])
        db.update("terms", t_id, fields)
        t = db.one("SELECT * FROM terms WHERE id=?", (t_id,))
        if not t:
            raise HTTPException(404, "term not found")
        _term_card(t)
        return t

    @app.delete("/api/terms/{t_id}")
    def api_term_delete(t_id: str):
        db.soft_delete("terms", t_id)
        services.remove_card(db, "term", t_id)
        return {"ok": True}

    @app.get("/api/concepts")
    def api_concept(term: str):
        """Concept page: every highlight, note and sentence on this term across all papers."""
        escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"  # % and _ in a term are literal text (ESCAPE '\' in the queries)
        return {
            "term": term,
            "glossary": db.all("SELECT * FROM terms WHERE lower(term)=lower(?) AND deleted=0", (term.strip(),)),
            "highlights": db.all(
                "SELECT h.*, d.title FROM highlights h JOIN documents d ON d.id=h.document_id"
                " WHERE h.deleted=0 AND d.deleted=0 AND (h.text LIKE ? ESCAPE '\\' OR h.note LIKE ? ESCAPE '\\') ORDER BY h.created_at DESC LIMIT 100",
                (like, like),
            ),
            "notes": db.all(
                "SELECT n.*, d.title FROM notes n JOIN documents d ON d.id=n.document_id"
                " WHERE n.deleted=0 AND d.deleted=0 AND n.text LIKE ? ESCAPE '\\' LIMIT 100",
                (like,),
            ),
            "mentions": db.all(
                "SELECT s.document_id, s.ord, s.text, d.title FROM sentences s JOIN documents d ON d.id=s.document_id"
                " WHERE s.deleted=0 AND d.deleted=0 AND s.text LIKE ? ESCAPE '\\' ORDER BY d.title, s.ord LIMIT 60",
                (like,),
            ),
        }

    # ---------------- review
    @app.get("/api/review/due")
    def api_due():
        return services.due_cards(db, settings_dict()["review_cap"])

    @app.get("/api/library/counts")
    def api_library_counts():
        # the numbers on Library's tabs: documents, study files, goals not finished, cards you can review now (the daily cap counts), terms
        due = services.due_cards(db, settings_dict()["review_cap"])
        return {
            "documents": db.scalar("SELECT COUNT(*) FROM documents WHERE deleted=0") or 0,
            "lectures": db.scalar("SELECT COUNT(*) FROM lectures WHERE deleted=0") or 0,
            "goals": db.scalar("SELECT COUNT(*) FROM quests WHERE deleted=0 AND status!='done'") or 0,
            "review_due": min(due["due_total"], due["cap_left"]),
            "terms": db.scalar("SELECT COUNT(*) FROM terms WHERE deleted=0 AND (is_concept=0 OR definition!='')") or 0,  # the ones the Glossary lists
        }

    @app.post("/api/review/{card_id}")
    def api_review(card_id: str, body: RatingIn):
        try:
            return services.review_card(db, card_id, body.rating)
        except KeyError as e:
            raise HTTPException(404, "card not found") from e

    @app.get("/api/cards")
    def api_cards(document_id: str | None = None):
        if document_id:
            return db.all("SELECT * FROM cards WHERE document_id=? AND deleted=0 ORDER BY created_at", (document_id,))
        return db.all("SELECT * FROM cards WHERE deleted=0 ORDER BY due LIMIT 500")

    # ---------------- ideas
    @app.get("/api/plan/counts")
    def api_plan_counts():
        # the number on Plan's Tasks tab: what is for now (today's tasks and the carried-over ones)
        today = dt.date.today().isoformat()
        return {"tasks_now": db.scalar(
            "SELECT COUNT(*) FROM todos WHERE deleted=0 AND (done_at IS NULL OR done_at='') AND due IS NOT NULL AND due!='' AND due<=?", (today,)) or 0}

    @app.get("/api/notes/counts")
    def api_notes_counts():
        # the numbers on the tabs of Notes. Think only counts what is already there: looking at a tab makes no new suggestions.
        today = dt.date.today().isoformat()
        return {
            "notes": db.scalar("SELECT COUNT(*) FROM pages WHERE deleted=0") or 0,
            "ideas": db.scalar("SELECT COUNT(*) FROM ideas WHERE deleted=0") or 0,
            "think": (db.scalar("SELECT COUNT(*) FROM suggestions WHERE status='new' AND deleted=0") or 0)
            + (db.scalar("SELECT COUNT(*) FROM daily_picks WHERE day=? AND status='new' AND deleted=0", (today,)) or 0),
        }

    @app.get("/api/ideas")
    def api_ideas():
        return db.all(
            "SELECT i.*, d.title AS document_title FROM ideas i LEFT JOIN documents d ON d.id=i.document_id"
            " WHERE i.deleted=0 ORDER BY i.created_at DESC"
        )

    @app.post("/api/ideas")
    def api_idea_create(body: IdeaIn):
        return db.insert("ideas", body.model_dump())

    @app.delete("/api/ideas/{i_id}")
    def api_idea_delete(i_id: str):
        db.soft_delete("ideas", i_id)
        ai.results.forget_document(db, i_id)  # a brainstorm about the idea goes out of sight with it
        return {"ok": True}

    # ---------------- compass: main quest, steps, energy, side quests
    compass.register(app, db)
    growth.register(app, db)
    lectures.register(app, db)
    journal.register(app, db)
    timer.register(app, db)
    planner.register(app, db)
    readplan.register(app, db, settings_dict)
    pages.register(app, db)
    search.register(app, db)
    related.register(app, db)
    organize.register(app, db)  # milestone 3.3, without a model: document tags, related documents, suggested tags
    tidy.register(app, db)  # milestone 5.2, without a model: what a good task lacks, and fixes code is sure of
    hub.register(app, db)
    think.register(app, db)
    passages.register(app, db)
    trash.register(app, db)  # milestone 5.1: delete and Undo on every kind of record you make, and on single AI results
    port = ai.register(app, db, settings_dict)  # the LLM port; with ai_mode off it connects to nothing

    # ---------------- sessions and stats
    @app.post("/api/sessions")
    def api_session_start(body: SessionIn):
        row = {**body.model_dump(), "started_at": now()}
        if body.document_id:  # where this reading session starts (a sentence ord)
            row["start_ord"] = row["last_ord"] = db.scalar("SELECT position FROM documents WHERE id=?", (body.document_id,))
        return db.insert("sessions", row)

    @app.patch("/api/sessions/{s_id}")
    def api_session_patch(s_id: str, body: SessionPatch):
        fields = body.model_dump(exclude_none=True)
        ended = fields.pop("ended", False)
        if ended:
            fields["ended_at"] = now()
        doc_id = db.scalar("SELECT document_id FROM sessions WHERE id=?", (s_id,))
        if doc_id:  # where the reader is now: the last one saved is where the session stopped
            fields["last_ord"] = db.scalar("SELECT position FROM documents WHERE id=?", (doc_id,))
        db.update("sessions", s_id, fields)
        return {"ok": True}

    @app.get("/api/stats")
    def api_stats():
        days = services.daily_stats(db, 28)
        return {"days": days, "streak": services.streak(days), "week": services.weekly_review(db)}

    # ---------------- settings, themes, export
    @app.get("/api/settings")
    def api_settings():
        return settings_dict()

    @app.put("/api/settings")
    def api_settings_put(body: dict[str, Any]):
        t = now()
        checked = {}
        def strings(v):
            if isinstance(v, str):
                yield v
            elif isinstance(v, dict):
                for x in v.values():
                    yield from strings(x)
            elif isinstance(v, list):
                for x in v:
                    yield from strings(x)

        for k, v in body.items():  # a value shaped like an API key is never stored, in any setting, at any depth (keys live in the credential store)
            if any(redact.looks_like_key(x) for x in strings(v)):
                raise HTTPException(422, f"{k}: that looks like an API key. Save it with the API key field in Settings → AI instead.")
        for k, v in body.items():  # the AI settings are checked first, so a bad one changes nothing
            if k in ai.settings.CHECKS:
                try:
                    checked[k] = ai.settings.check(k, v)
                except ValueError as e:
                    raise HTTPException(422, f"{k}: {e}") from None
        for k, v in {**body, **checked}.items():
            if k not in DEFAULT_SETTINGS:
                continue
            db.execute(
                "INSERT INTO settings (key, value, updated_at, id, device_id) VALUES (?,?,?,lower(hex(randomblob(16))),?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at,"
                " device_id=excluded.device_id, deleted=0",
                (k, json.dumps(v), t, db.device),
            )
        if checked:
            port.settings_changed()  # switching AI off stops the calls that are running
            ai.log.purge(db)  # a shorter time for the AI log applies at once
        return settings_dict()

    @app.get("/api/themes")
    def api_themes():
        out = []
        for f in sorted(config.THEMES_DIR.glob("*/theme.json")):
            try:
                data = json.loads(f.read_text("utf-8"))
                data["id"] = f.parent.name
                data["has_scene"] = (f.parent / "scene.js").exists()
                out.append(data)
            except ValueError:
                log.warning("Bad theme file %s", f)
        return out

    @app.get("/api/ambience")
    def api_ambience():
        """Numbers the animated themes turn into progress (one star per card reviewed today), and today's energy."""
        checkin = compass.checkin_today(db)
        return {"reviews_today": services.reviews_today(db), "energy_today": checkin["energy"] if checkin else None}

    @app.post("/api/export/all")
    def api_export_all():
        return {"path": services.export_all(db)}

    @app.post("/api/backup")
    def api_backup():
        return {"path": str(db.backup("manual-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")))}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    return app
