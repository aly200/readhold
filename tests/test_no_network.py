"""Readhold connects to nothing by itself. The one connection it can make is to the AI model the user chose,
and only the LLM adapters in `readhold/ai/` may open it. These checks keep it that way."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# modules that open outgoing connections; only the package below may import one
CLIENTS = {"httpx", "requests", "aiohttp", "urllib3", "httplib2", "http.client", "urllib.request", "ftplib", "smtplib", "websockets", "trafilatura"}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


ALLOWED = ROOT / "readhold" / "ai"  # the LLM port and its adapters: the single exception


def _clients(path: Path) -> set[str]:
    return {n for n in _imports(path) if any(n == c or n.startswith(c + ".") for c in CLIENTS)}


# lower-level ways out, each allowed in one place for one reason (the entry point binds its own 127.0.0.1 port and
# opens its own address in your browser); anywhere else they fail this test
LOW_LEVEL = {"socket": {"readhold/__main__.py"}, "webbrowser": {"readhold/__main__.py"}, "ssl": set(), "subprocess": set()}


def test_no_module_opens_a_socket_a_browser_or_a_program_except_the_entry_point():
    for path in sorted((ROOT / "readhold").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        for mod in _imports(path):
            top = mod.split(".")[0]
            if top in LOW_LEVEL:
                assert name in LOW_LEVEL[top], f"{name} imports {mod}"


def test_only_the_llm_adapters_import_a_network_client():
    for path in sorted((ROOT / "readhold").rglob("*.py")):
        if ALLOWED in path.parents:
            continue
        used = _clients(path)
        assert not used, f"{path.relative_to(ROOT)} imports {sorted(used)}"


def test_the_exception_is_exactly_one_package_and_one_client():
    users = {p.relative_to(ROOT).as_posix(): _clients(p) for p in sorted(ALLOWED.rglob("*.py")) if _clients(p)}
    assert users, "readhold/ai/ should hold the adapters"
    # one file opens connections, with one client library; the rest of the package goes through it
    assert users == {"readhold/ai/adapters.py": {"httpx"}}, users


def test_nothing_outside_the_ai_package_reaches_into_the_adapters():
    """Features call the port (`readhold.ai`), never an adapter or the HTTP client behind it."""
    for path in sorted((ROOT / "readhold").rglob("*.py")):
        if ALLOWED in path.parents:
            continue
        names = _imports(path)
        assert not {n for n in names if n.startswith("readhold.ai.adapters")}, path
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and (node.module or "").startswith("ai.adapters"):
                raise AssertionError(f"{path.relative_to(ROOT)} imports the adapters")
            if isinstance(node, ast.ImportFrom) and node.level and node.module == "ai":
                assert "adapters" not in {a.name for a in node.names}, path


def test_the_front_end_only_talks_to_its_own_server():
    for path in sorted((ROOT / "web" / "src").rglob("*.ts")):
        text = path.read_text("utf-8")
        for call in ("fetch(\"http", "fetch(`http", "fetch('http", "new WebSocket(", "new EventSource(", "sendBeacon("):
            assert call not in text, f"{path.relative_to(ROOT)} has {call}"


def test_there_is_no_link_import(client):
    assert client.post("/api/import/url", json={"url": "https://example.org/paper"}).status_code in (404, 405)


def test_the_calm_tools_are_gone(client):
    """Unstick, Steady me, the notes from steady you and Guess vs. reality were removed on 2026-11-25."""
    assert client.get("/api/calm").status_code == 404
    assert client.get("/api/calm/notes").status_code == 404
    settings = client.get("/api/settings").json()
    assert not {"unstick_button", "guess_ask", "steady_pattern"} & set(settings)
    run = client.post("/api/timer/start", json={"kind": "focus", "minutes": 5, "guess": 7}).json()
    assert "guess_hard" not in run  # an old page that still sends a guess is not an error, and nothing is stored


def test_no_telemetry_can_be_recorded_or_exported(monkeypatch):
    """FastAPI 0.15x brought OpenTelemetry hooks (as opentelemetry-api). Readhold switches all of them off, even when
    the environment asks for export, and no OpenTelemetry SDK or exporter is installed to send anything."""
    import importlib.metadata as md

    from readhold import server

    assert server.NO_TELEMETRY == {"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://example.invalid")
    from fastapi import FastAPI
    probe = FastAPI(telemetry=server.NO_TELEMETRY)
    assert probe._telemetry["auto_configure"] is False and not probe._telemetry["tracing"]
    installed = {d.metadata["Name"].lower() for d in md.distributions()}
    assert not {n for n in installed if n.startswith("opentelemetry-") and n != "opentelemetry-api"}

