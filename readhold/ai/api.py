"""The routes of the AI settings: status, the API key, Test connection, the profiles and the AI log.

No route here returns a key. No route takes a prompt from the page: the front end never builds prompts or
calls a model, it asks the server to.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import config
from ..db import DB
from . import ask, brainstorm, chat, digest, explain, guard, library, notechat, notes, organize, plan, results, resume, tidy, why
from . import keys, profiles
from . import log as ai_log
from .port import AIError, Port

log = logging.getLogger(__name__)
TEST_MESSAGE = "Reply with the single word: ready"  # what Test connection sends; nothing of the user's


class KeyIn(BaseModel):
    provider: str
    key: str = Field(max_length=600)


class TestIn(BaseModel):
    call_id: str | None = Field(None, max_length=64)


class CancelIn(BaseModel):
    call_id: str = Field(max_length=64)


def register(app: FastAPI, db: DB, settings: Callable[[], dict]) -> Port:
    port = Port(db, settings)
    app.state.ai = port
    app.state.db = db
    try:
        ai_log.purge(db)  # the 30-day rule, applied at every start
    except Exception:  # noqa: BLE001  (never a reason not to open the app)
        log.exception("Could not purge the AI log")
    try:
        guard.flag_new_documents(db)  # documents imported before the warning badge existed
    except Exception:  # noqa: BLE001
        log.exception("Could not look at the documents for flagged text")

    resume.register(app, db, port)  # milestone 1.3: "where you left off"
    explain.register(app, db, port)  # milestone 1.4: explain a selected passage
    digest.register(app, db, port)  # milestone 1.5: the shape of a document, map-reduce in the background
    ask.register(app, db, port)  # milestone 2.2: a question about the document you are reading
    library.register(app, db, port)  # milestone 2.3: a question across the whole library, a bounded loop
    notes.register(app, db, port)  # milestone 2.4: study notes, flashcards or a quiz, kept only when accepted
    plan.register(app, db, port)  # milestone 3.1: a model suggests the order and levels of a reading plan; code schedules it
    brainstorm.register(app, db, port)  # milestone 3.2: ideas in samples from three angles, grouped and ranked by a critic call
    organize.register(app, db, port)  # milestone 3.3: tags that reuse yours and related documents, suggested; you add them
    tidy.register(app, db, port)  # milestone 5.2: a rewrite of tasks, a note or a routine, proposed only; the page applies what you accept
    chat.register(app, db, port)  # milestone 5.3: tasks drafted from what you type; added only when you click, with Undo
    notechat.register(app, db, port)  # milestone 5.4: tell a model what to do with a note; the page uses what you choose, with Undo
    why.register(app, db)  # milestone 4.2: "Why did it say this?", read from the AI log and the prompt files; no model call

    @app.get("/api/ai/status")
    def api_ai_status():
        return port.status()

    @app.put("/api/ai/key")
    def api_ai_key(body: KeyIn):
        """Store the key in the credential store. The answer says only that one is set."""
        name = body.provider
        if name not in keys.PROVIDERS:
            raise HTTPException(422, "unknown provider")
        try:
            keys.save(name, body.key)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except Exception as e:  # noqa: BLE001
            log.warning("The credential store refused the key (%s).", type(e).__name__)
            raise HTTPException(500, "The credential store of this computer could not save the key.") from None
        return {"provider": name, "key_set": True}

    @app.delete("/api/ai/key")
    def api_ai_key_delete(provider: str):  # noqa: A002  (the query parameter is named provider)
        if provider not in keys.PROVIDERS:
            raise HTTPException(422, "unknown provider")
        try:
            keys.clear(provider)
        except Exception as e:  # noqa: BLE001
            log.warning("The credential store could not clear the key (%s).", type(e).__name__)
            raise HTTPException(500, "The credential store of this computer could not clear the key.") from None
        return {"provider": provider, "key_set": False}

    @app.post("/api/ai/test")
    def api_ai_test(body: TestIn):
        """Test connection: one tiny call with the settings as they are. With AI off it connects to nothing."""
        try:
            reply = port.complete("test", "", TEST_MESSAGE, call_id=body.call_id)
        except AIError as e:
            return {"ok": False, "code": e.code, "message": e.message}
        return {"ok": True, "provider": reply.provider, "model": reply.model, "latency_ms": reply.latency_ms,
                "log_id": reply.log_id, "warning": reply.warning}

    @app.post("/api/ai/cancel")
    def api_ai_cancel(body: CancelIn):
        return {"cancelled": port.cancel(body.call_id)}

    @app.get("/api/ai/profiles")
    def api_ai_profiles():
        return {"profiles": profiles.load(), "defaults": profiles.defaults()}

    @app.put("/api/ai/profiles")
    def api_ai_profiles_put(body: dict[str, Any]):
        """Replace your changes to the profiles ({} = back to the defaults)."""
        try:
            return {"profiles": profiles.save(body), "defaults": profiles.defaults()}
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/ai/log")
    def api_ai_log(limit: int = 50):
        return {"rows": ai_log.recent(db, limit), "keep_days": ai_log.days(db)}

    @app.delete("/api/ai/log")
    def api_ai_log_clear():
        library.cancel(port)  # questions and brainstorms that are running would write new rows right after
        brainstorm.cancel(port)
        port.cancel_all()  # and every other call that is running: none of them keeps a result after the clear
        ai_log.clear(db)
        digest.stop()  # a digest that is running would write new rows right after
        for pattern in ("readhold-ai-export-*.json", "foothold-ai-export-*.json"):  # files of the AI export (removed on 2026-11-26) held all of it too
            for f in config.exports_dir().glob(pattern):
                f.unlink(missing_ok=True)
        results.clear_all(db)  # the recaps, explanations and digests Readhold kept go too; notes you saved from them are yours and stay
        return {"ok": True}

    return port
