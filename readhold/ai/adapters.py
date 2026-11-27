"""The LLM adapters: the only code in Readhold that opens a network connection.

Each adapter turns one request of the port into one HTTP POST for its provider and reads the answer back as
plain text. `tests/test_no_network.py` allows a network client in this file and nowhere else.

What an adapter never does: it gives the model no tools, follows no redirect, reads no proxy or key from the
environment, and does nothing with the answer except hand its text to the port. An answer is untrusted text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from .where import DEFAULT_LOCAL, LOCAL_HOSTS, destination, is_local, leaves_computer  # noqa: F401  (where text goes: no network code)

MAX_REPLY_BYTES = 2_000_000  # a reply larger than this is dropped, whatever sends it
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# the models used when Settings name none: {provider: {size: model}}
CLOUD_DEFAULTS = {"anthropic": {"strong": "claude-opus-5-5", "small": "claude-haiku-5-5"}, "openai": {"strong": "", "small": ""}}


@dataclass
class Ask:
    """One request, with no provider detail in it."""

    model: str
    system: str
    user: str
    params: dict  # temperature, top_p, min_p, max_output_tokens: whatever the profile holds
    schema: dict | None = None  # a JSON schema, when the answer must be JSON


@dataclass
class Answer:
    text: str
    tokens_in: int | None = None  # None: the server did not say
    tokens_out: int | None = None


class AdapterError(Exception):
    """A call that failed. `code` is one of: offline, auth, model, busy, refused, bad_reply, error."""

    def __init__(self, code: str, detail: str = "", status: int = 0, retry: bool = False):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail, self.status, self.retry = code, detail, status, retry


def endpoint_warning(url: str) -> str:
    """What the user should know about a model server address. Empty for a server on this computer."""
    if is_local(url):
        return ""
    away = "This model server is not on this computer: text you send to it leaves this computer."
    if urlsplit(url).scheme != "https":
        return away + " The connection is not encrypted (no HTTPS), so others on the network can read it."
    return away


def _messages(ask: Ask) -> list[dict]:
    out = [{"role": "system", "content": ask.system}] if ask.system else []
    return out + [{"role": "user", "content": ask.user}]


def _pick(params: dict, names: dict[str, str]) -> dict:
    """The parameters this provider understands, under its own names. The rest are dropped."""
    return {theirs: params[ours] for ours, theirs in names.items() if params.get(ours) is not None}


@dataclass
class Ollama:
    """A local Ollama server (its own API: POST /api/chat)."""

    endpoint: str
    provider: str = "local"

    def request(self, ask: Ask) -> tuple[str, dict, dict]:
        body: dict = {
            "model": ask.model,
            "messages": _messages(ask),
            "stream": False,
            "options": _pick(ask.params, {"temperature": "temperature", "top_p": "top_p", "min_p": "min_p", "max_output_tokens": "num_predict"}),
        }
        if ask.schema:
            body["format"] = ask.schema  # Ollama holds the answer to the schema
        return self.endpoint.rstrip("/") + "/api/chat", {}, body

    def read(self, data: dict) -> Answer:
        return Answer(_text(data.get("message", {}).get("content")), _count(data.get("prompt_eval_count")), _count(data.get("eval_count")))


@dataclass
class OpenAICompatible:
    """A local server that speaks the OpenAI chat API: llama.cpp, LM Studio, vLLM, or Ollama under /v1."""

    endpoint: str
    provider: str = "local"

    def request(self, ask: Ask) -> tuple[str, dict, dict]:
        base = self.endpoint.rstrip("/")
        if not urlsplit(base).path:
            base += "/v1"
        body = {"model": ask.model, "messages": _messages(ask), "stream": False,
                **_pick(ask.params, {"temperature": "temperature", "top_p": "top_p", "max_output_tokens": "max_tokens"})}
        return base + "/chat/completions", {}, body

    def read(self, data: dict) -> Answer:
        return _read_openai(data)


@dataclass
class Anthropic:
    """Claude, with the user's own key (POST /v1/messages)."""

    key: str = field(repr=False)
    provider: str = "anthropic"

    def request(self, ask: Ask) -> tuple[str, dict, dict]:
        # Current Claude models refuse temperature, top_p and top_k, so no sampling parameter is sent.
        # They think before they answer and the thinking counts as output, hence the floor under max_tokens;
        # the port still cuts the answer to the profile's length.
        body: dict = {"model": ask.model, "max_tokens": max(1024, int(ask.params.get("max_output_tokens") or 1024)), "messages": [{"role": "user", "content": ask.user}]}
        if ask.system:
            body["system"] = ask.system
        return ANTHROPIC_URL, {"x-api-key": self.key, "anthropic-version": ANTHROPIC_VERSION}, body

    def read(self, data: dict) -> Answer:
        if data.get("stop_reason") == "refusal":
            raise AdapterError("refused")
        blocks = data.get("content") if isinstance(data.get("content"), list) else []
        text = "".join(_text(b.get("text")) for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        sent = [_count(usage.get(k)) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
        return Answer(text, sum(n for n in sent if n) if sent[0] is not None else None, _count(usage.get("output_tokens")))


@dataclass
class OpenAI:
    """OpenAI, with the user's own key (POST /v1/chat/completions)."""

    key: str = field(repr=False)
    provider: str = "openai"

    def request(self, ask: Ask) -> tuple[str, dict, dict]:
        names = {"max_output_tokens": "max_completion_tokens"}
        if not ask.model.startswith(("o1", "o3", "o4", "gpt-5")):  # reasoning models take no sampling parameters
            names.update(temperature="temperature", top_p="top_p")
        body = {"model": ask.model, "messages": _messages(ask), **_pick(ask.params, names)}
        return OPENAI_URL, {"authorization": f"Bearer {self.key}"}, body

    def read(self, data: dict) -> Answer:
        return _read_openai(data)


def _read_openai(data: dict) -> Answer:
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return Answer(_text(message.get("content") if isinstance(message, dict) else None), _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens")))


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def local(api: str, endpoint: str):
    return Ollama(endpoint) if api == "ollama" else OpenAICompatible(endpoint)


def cloud(provider: str, key: str):
    return {"anthropic": Anthropic, "openai": OpenAI}[provider](key)


def open_client(timeout: float, transport=None) -> httpx.AsyncClient:
    """One client for one call. No redirects are followed, and no proxy, certificate file or credential is
    taken from the environment: the request goes to the address in Settings and nowhere else."""
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
        follow_redirects=False,
        trust_env=False,
        headers={"user-agent": "Readhold"},
    )


def stand_in(answer) -> httpx.MockTransport:
    """A transport that never opens a connection: each request body (an Ollama /api/chat request, as a dict) is handed
    to `answer`, and the dict it returns is the reply. For the evaluation harness's stand-in model (`readhold.eval`)."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answer(json.loads(request.content)))

    return httpx.MockTransport(handle)


async def send(client: httpx.AsyncClient, adapter, ask: Ask) -> Answer:
    """POST the request and read the answer. Raises AdapterError, or TimeoutError when it is too slow."""
    url, headers, body = adapter.request(ask)
    raw = bytearray()
    try:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            status = response.status_code
            async for chunk in response.aiter_bytes():
                raw += chunk
                if len(raw) > MAX_REPLY_BYTES:
                    raise AdapterError("bad_reply", "the reply was too large", status)
    except httpx.TimeoutException:
        raise TimeoutError from None
    except httpx.ConnectError as e:
        raise AdapterError("offline", type(e).__name__) from None
    except httpx.HTTPError as e:  # the connection broke while talking
        raise AdapterError("error", type(e).__name__, retry=True) from None
    if status != 200:
        said = _server_message(raw)
        if status in (401, 403):
            raise AdapterError("auth", said, status)
        if status == 404:
            raise AdapterError("model", said, status)
        if status == 429 or status >= 500:
            raise AdapterError("busy", said, status, retry=True)
        raise AdapterError("error", said, status)
    try:
        data = json.loads(raw)
    except ValueError:
        raise AdapterError("bad_reply", "the reply was not JSON", status, retry=True) from None
    if not isinstance(data, dict):
        raise AdapterError("bad_reply", "the reply was not an object", status, retry=True)
    return adapter.read(data)


def _server_message(raw: bytes) -> str:
    """A short piece of what the server said, for the log only (the port removes secrets from it)."""
    text = bytes(raw[:2000]).decode("utf-8", "replace")
    try:
        data = json.loads(text)
        err = data.get("error") if isinstance(data, dict) else None
        text = err.get("message", text) if isinstance(err, dict) else (err if isinstance(err, str) else text)
    except ValueError:
        pass
    return " ".join(str(text).split())[:200]
