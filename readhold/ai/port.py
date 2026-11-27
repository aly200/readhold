"""The LLM port: the one way the app talks to a model.

    reply = port.complete("explain", system, user)            # reply.text
    reply = port.complete("digest", system, user, schema=M)   # reply.data, checked against the pydantic model M

A feature names its task and hands over text. Everything else is decided here: which provider and model
(Settings), how varied and how long (the task's profile), and the limits every call has:

- AI off means off: the call is refused before anything that could open a connection exists.
- a timeout, and at most one retry (after a server error or an answer that fails its schema);
- an output length cap; at most 2 calls at once; a daily token budget per provider (warning at 80%, stop at 100%);
- every call can be cancelled, and switching AI off cancels all of them;
- one row in `ai_log` per call.

The model gets no tools and no way to reach the network. What it returns is text: it is never run, opened as a
path or followed as a link, here or by the caller.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .. import redact
from ..db import DB, new_id
from . import adapters, keys, profiles
from . import log as ai_log

log = logging.getLogger(__name__)

MAX_AT_ONCE = 2
MAX_INPUT_CHARS = 400_000  # a hard cap on what one call may send; features budget far below it
CHARS_PER_TOKEN = 8  # the output cap in characters is the profile's token cap times this (generous on purpose)
WARN_AT = 0.8
MODES = ("off", "local", "cloud")


# ------------------------------------------------------------------ errors, in words the UI can show
class AIError(Exception):
    code = "error"
    message = "The AI call failed."
    log_id = ""  # the AI log row of the failed call, when one was written

    def __init__(self, message: str | None = None, code: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.code = code or self.code


class AIOff(AIError):
    code, message = "off", "AI is off. You can switch it on in Settings."


class NotSetUp(AIError):
    code, message = "setup", "Choose a model in Settings first."


class NoKey(AIError):
    code, message = "no_key", "Cloud mode needs your API key. Save it in Settings first."


class BudgetReached(AIError):
    code, message = "budget", "Today's token budget for this provider is used up. It starts again tomorrow; you can also raise it in Settings."


class TimedOut(AIError):
    code, message = "timeout", "The model took too long, so the call was stopped."


class Cancelled(AIError):
    code, message = "cancelled", "Stopped."


class ModeChanged(AIError):
    code, message = "changed", "The AI mode or the model server changed while this was being prepared. Nothing was sent; try again."


class CouldNotGenerate(AIError):
    code, message = "invalid", "Couldn't generate a usable answer."


class TooLong(AIError):
    code, message = "too_long", "That is too much text for one AI call."


class ProviderError(AIError):
    MESSAGES = {
        "offline": "The model server did not answer. Is it running?",
        "auth": "The provider refused the API key.",
        "model": "The server does not know this model. Check its name in Settings.",
        "busy": "The model server is busy or failing right now. Try again in a moment.",
        "refused": "The model declined this request.",
        "bad_reply": "The model server sent an answer that could not be read.",
        "error": "The model server returned an error.",
    }

    def __init__(self, code: str):
        super().__init__(self.MESSAGES.get(code, self.MESSAGES["error"]), code if code in self.MESSAGES else "error")


@dataclass
class Reply:
    text: str
    data: Any  # the checked JSON when a schema was given, else None
    log_id: str
    provider: str
    model: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    warning: str = ""  # set when the day's budget is 80% used


# ------------------------------------------------------------------ the port
class Port:
    def __init__(self, db: DB, settings: Callable[[], dict], transport=None):
        self.db = db
        self.settings = settings  # read on every call, so a settings change is all it takes to switch
        self.transport = transport  # tests put a mock here; None means a real connection
        self.retry_wait = 0.5  # seconds before the one retry
        self._loop: asyncio.AbstractEventLoop | None = None
        self._slots: asyncio.Semaphore | None = None
        self._active: dict[str, asyncio.Task] = {}
        self._start = threading.Lock()

    # ---------- the public surface
    def complete(self, task: str, system: str, user: str, schema: type[BaseModel] | None = None, *, call_id: str | None = None, prompt_version: str = "",
                 expect_mode: str | None = None, expect_away: bool | None = None) -> Reply:
        """Ask the model. Blocks until the answer, an error (an `AIError`), the timeout or a cancel.
        Call it from a worker thread, never from the event loop of the server. `expect_mode`: the mode the text was
        prepared for (`guard.ask` passes it); if the setting changed since, nothing is sent."""
        s = self.settings()
        if s.get("ai_mode") not in ("local", "cloud"):
            raise AIOff()  # before any thread, client or socket exists
        if (expect_mode is not None and s.get("ai_mode") != expect_mode) or (expect_away is not None and adapters.leaves_computer(s) != expect_away):
            raise ModeChanged()  # text packed to stay on this computer never goes anywhere else
        profile = profiles.load().get(task)
        if profile is None:
            raise ValueError(f"no AI profile for task {task!r}")
        future = asyncio.run_coroutine_threadsafe(self._tracked(call_id or new_id(), task, system or "", user or "", schema, profile, s, prompt_version), self._ensure_loop())
        return future.result()

    def cancel(self, call_id: str) -> bool:
        """Stop one running call. True if there was one."""
        task = self._active.get(call_id)
        if not task or not self._loop:
            return False
        self._loop.call_soon_threadsafe(task.cancel)
        return True

    def cancel_all(self) -> int:
        """Stop every running call (the kill switch)."""
        running = list(self._active)
        return sum(1 for call_id in running if self.cancel(call_id))

    def use_stand_in(self, answer: Callable[[dict], dict]) -> None:
        """Answer every call in-process with `answer` (request body -> Ollama reply) instead of a model server; nothing
        connects anywhere. Only the evaluation harness's stand-in mode uses it; every guard still runs."""
        self.transport = adapters.stand_in(answer)
        self.retry_wait = 0

    def settings_changed(self) -> None:
        s = self.settings()
        where = (s.get("ai_mode"), adapters.leaves_computer(s))
        if where[0] not in ("local", "cloud") or where != getattr(self, "_where", where):
            self.cancel_all()  # switched off, or to another kind of destination: what runs was prepared for the other one
        self._where = where

    def status(self) -> dict:
        """What the Settings page and the status chip show. It never contains a key, only whether one is set."""
        s = self.settings()
        mode = s.get("ai_mode") if s.get("ai_mode") in MODES else "off"
        cloud = s.get("ai_cloud_provider", "anthropic")
        out = {"mode": mode, "cloud_provider": cloud, "key_set": cloud in keys.PROVIDERS and keys.is_set(cloud), "logged": ai_log.count(self.db),
               "provider": "", "model": "", "ready": False, "problem": "", "warning": "", "usage": None}
        if mode == "off":
            return out
        provider = "local" if mode == "local" else cloud
        out["provider"] = provider
        out["model"] = self._model(s, mode, "strong")
        if mode == "local":
            out["warning"] = adapters.endpoint_warning(s.get("ai_local_endpoint", ""))
        if not out["model"]:
            out["problem"] = NotSetUp.message
        elif mode == "cloud" and not out["key_set"]:
            out["problem"] = NoKey.message
        out["ready"] = not out["problem"]
        used, budget = ai_log.tokens_today(self.db, provider), self._budget(s, mode)
        state = "ok" if not budget or used < WARN_AT * budget else ("warn" if used < budget else "stop")
        out["usage"] = {"used": used, "budget": budget, "state": state}
        return out

    # ---------- inside
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="readhold-ai", daemon=True).start()
                self._loop = loop
            return self._loop

    @staticmethod
    def _model(s: dict, mode: str, size: str) -> str:
        if mode == "local":
            return (s.get("ai_local_small_model") if size == "small" else "") or s.get("ai_local_model") or ""
        provider = s.get("ai_cloud_provider", "")
        chosen = (s.get("ai_cloud_small_model") if size == "small" else "") or s.get("ai_cloud_model") or ""
        fallback = adapters.CLOUD_DEFAULTS.get(provider, {})
        if chosen:
            return chosen
        return fallback.get(size) or fallback.get("strong") or ""

    @staticmethod
    def _budget(s: dict, mode: str) -> int:
        try:
            return max(0, int(s.get("ai_budget_local" if mode == "local" else "ai_budget_cloud") or 0))
        except (TypeError, ValueError):
            return 0

    async def _tracked(self, call_id: str, *args) -> Reply:
        self._active[call_id] = asyncio.current_task()
        try:
            return await self._call(*args)
        finally:
            self._active.pop(call_id, None)

    async def _call(self, task: str, system: str, user: str, schema, profile: dict, s: dict, prompt_version: str = "") -> Reply:
        started = time.monotonic()
        mode = s["ai_mode"]
        provider = "local" if mode == "local" else s.get("ai_cloud_provider", "")
        model = self._model(s, mode, profile.get("model", "strong"))
        checks: dict = {}
        if adapters.leaves_computer(s):
            # the last gate before text leaves this computer: a feature that forgot its own guard still sends no secret
            system, n_sys = redact.scrub_all(system)
            user, n_user = redact.scrub_all(user)
            checks["secrets_redacted"] = n_sys + n_user
        row = {"task": task, "provider": provider, "model": model, "prompt_version": prompt_version[:80],
               "input_hash": ai_log.digest(system, user), "input_preview": ai_log.preview(user)}
        used = {"in": 0, "out": 0, "attempts": 0}

        def record(outcome: str, error: str = "", output: str = "") -> str:
            return ai_log.write(
                self.db, **row, output_preview=ai_log.preview(output), latency_ms=int((time.monotonic() - started) * 1000),
                tokens_in=used["in"], tokens_out=used["out"], attempts=used["attempts"], checks=json.dumps(checks),
                outcome=outcome, error=redact.clean(error)[:300],
            )

        def fail(outcome: str, error: AIError, detail: str = "") -> AIError:
            error.log_id = record(outcome, detail or error.code)  # so a feature can still list the failed call ("Why did it say this?")
            return error

        try:
            budget = self._budget(s, mode)
            spent = ai_log.tokens_today(self.db, provider)
            if budget and spent >= budget:
                raise fail("budget", BudgetReached())
            if not model:
                raise fail("setup", NotSetUp())
            if len(system) + len(user) > MAX_INPUT_CHARS:
                raise fail("error", TooLong())
            if mode == "local":
                adapter = adapters.local(s.get("ai_local_api", "ollama"), s.get("ai_local_endpoint", ""))
            else:
                key = keys.get(provider) if provider in keys.PROVIDERS else None
                if not key:
                    raise fail("no_key", NoKey())  # the cloud adapter is not even built without a key
                adapter = adapters.cloud(provider, key)
            ask = adapters.Ask(model, system, user, {k: v for k, v in profile.items() if k != "model"}, schema.model_json_schema() if schema else None)
            cap = int(profile.get("max_output_tokens", 512)) * CHARS_PER_TOKEN
            timeout = min(600.0, max(0.05, float(s.get("ai_timeout_s") or 60)))

            if self._slots is None:
                self._slots = asyncio.Semaphore(MAX_AT_ONCE)
            async with self._slots:
                text, data = "", None
                for attempt in (1, 2):  # the call, and at most one retry
                    used["attempts"] = attempt
                    try:
                        async with asyncio.timeout(timeout):
                            async with adapters.open_client(timeout, self.transport) as client:
                                answer = await adapters.send(client, adapter, ask)
                    except TimeoutError:
                        raise fail("timeout", TimedOut()) from None
                    except adapters.AdapterError as e:
                        if e.retry and attempt == 1:
                            await asyncio.sleep(self.retry_wait)
                            continue
                        log.warning("AI call failed: task=%s provider=%s status=%s %s", task, provider, e.status, e)
                        raise fail("error", ProviderError(e.code), f"{e.code} {e.status or ''} {e.detail}".strip()) from None
                    text = answer.text
                    if answer.tokens_in is None or answer.tokens_out is None:
                        checks["tokens_estimated"] = True
                    used["in"] += answer.tokens_in if answer.tokens_in is not None else (len(system) + len(user)) // 4
                    used["out"] += answer.tokens_out if answer.tokens_out is not None else len(text) // 4
                    if len(text) > cap:
                        text, checks["truncated"] = text[:cap], True
                    text = redact.strip_known(text)  # a server that repeats the key back does not get it into the app
                    if schema is None:
                        if text.strip():
                            break
                        problem = "empty answer"
                    else:
                        try:
                            data = schema.model_validate_json(_json_part(text)).model_dump()
                            checks["schema"] = True
                            break
                        except ValidationError as e:
                            checks["schema"] = False
                            checks["schema_failures"] = checks.get("schema_failures", 0) + 1  # kept after a retry that worked
                            problem = f"{e.error_count()} schema errors"
                    if attempt == 1:
                        await asyncio.sleep(self.retry_wait)
                        continue
                    raise fail("invalid", CouldNotGenerate(), problem)
        except asyncio.CancelledError:
            stopped = Cancelled()
            stopped.log_id = record("cancelled")
            raise stopped from None

        log_id = record("ok", output=text)
        total = spent + used["in"] + used["out"]
        warning = ""
        if budget and total >= WARN_AT * budget:
            warning = f"You have used {min(999, round(100 * total / budget))}% of today's token budget for this provider (the warning starts at 80%)."
        return Reply(text, data, log_id, provider, model, int((time.monotonic() - started) * 1000), used["in"], used["out"], warning)


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.S)


def _json_part(text: str) -> str:
    """The JSON object inside an answer: without a code fence around it or words before and after."""
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    a, b = text.find("{"), text.rfind("}")
    return text[a : b + 1] if 0 <= a < b else text
