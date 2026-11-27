# Chapter 1: Back-end core and import

This chapter covers the part of the Python server that starts the app, guards every request, stores data, and turns a file or pasted text into a readable document. It also covers the reader's own routes (documents, questions, highlights, notes, terms, cards, review, sessions, ideas, settings) and the rule-based text code behind them. Other features (goals, lectures, tasks, notes pages, and so on) live in their own modules and have their own chapters; `server.py` only wires them in.

Files covered:

| File | Job |
|---|---|
| `readhold/__main__.py` | Start-up: flags, port, token, server thread, window |
| `readhold/config.py` | Paths, device id, the file size limit, logging |
| `readhold/db.py` | The `DB` class, migrations, backups |
| `readhold/server.py` | `create_app()`: the guard, static files, settings, the reader's routes |
| `readhold/bodies.py` | `Body`: the base of request models that hold a required text |
| `readhold/services.py` | Question templates, FSRS cards, summary sheet, exports, home, stats |
| `readhold/store.py` | Saves a `ParsedDoc` as rows; loads a document for the reader |
| `readhold/trash.py` | Delete and Undo on every kind of record the reader makes, and on single AI results (milestone 5.1; section 7b) |
| `readhold/winicon.py` | Window icon on Windows |
| `readhold/importers/__init__.py` | Import entry points and the plain-text fallback |
| `readhold/importers/model.py` | `ParsedDoc`, `PSection`, `PPara`, `ImportFailed` |
| `readhold/importers/pdf_import.py` | PDF through PDFium |
| `readhold/importers/markdown_import.py` | Markdown and plain text |
| `readhold/importers/code_import.py` | Code files: one section per top-level definition |
| `readhold/text.py` | Sentence splitting, section kinds, math helpers |
| `readhold/density.py` | The density score |
| `readhold/terms.py` | Definition and acronym finding |

Call direction, top to bottom:

```
__main__  ->  config, db.open_db, server.create_app, winicon
server    ->  services, store, importers, terms, text, config, db, bodies  (+ every feature module's register())
services  ->  store, text, terms, config, db, fsrs
importers ->  store.save_parsed, config, text
store     ->  density, passages, text, config, db
```

`passages.py` (the full-text index of sections, chapter 3, section 4b) imports only `db`. `store.save_parsed` and five routes in `server.py` (delete, restore, section rename, merge-up, split) call `passages.reindex`.

`server.py` also imports the AI package (chapter 3, section 7b): `ai.register` in `create_app` (called right after `passages.register`; it also registers the two routes of the Resume briefing, `ai/resume.py`, and the two of Explain selection, `ai/explain.py`), and `ai.guard.flag_document` after every import (`_import_result`). `ai/resume.py` reads `passages.last_session`. The importers and `store.py` import nothing from `ai`.

`text.py`, `density.py`, `terms.py` and `bodies.py` import nothing from the project. `trash.py` imports only `db` (and `growth._creates_cycle` inside a function); `server.py` calls `trash.register` after `passages.register`.

**Versions** that matter for this chapter (`pyproject.toml`, locked in `uv.lock`, 2026-11-26): fastapi 0.162.5 and starlette 1.10.0 (both pinned since 2026-11-26, when an OSV check found advisories in starlette 0.49.3, python-multipart 0.0.20, mistune 3.1.3, lxml 5.4.0 and pytest 8.3.5; each was moved to a fixed release at least two weeks old, and the check now finds none), uvicorn 0.34.2, python-multipart 0.0.33, pydantic 2.14.3 (locked), pypdfium2 5.15.0, pillow 13.0.0, mistune 3.4.0, fsrs 5.1.3, wordfreq 3.1.1, lxml 6.1.3, pywebview 5.4; for the tests pytest 9.2.0 and reportlab 5.1.0. FastAPI 0.162 brings `opentelemetry-api` (Apache-2.0); `server.NO_TELEMETRY` switches all of FastAPI's telemetry off, and no OpenTelemetry SDK or exporter is installed (`tests/test_no_network.py`).

---

## 1. Start-up sequence

`python -m readhold` runs `main()` in `__main__.py`.

1. **Parse flags.** `--browser`, `--serve`, `--port N` (default 0 = random), `--token T` (default empty = random).
2. **Logging.** `config.setup_logging()` adds a rotating file handler for `data/logs/readhold.log`. Its formatter removes key-shaped text from every line (`redact.RedactingFormatter`).
3. **Socket, port and token.** `bind(args.port)` binds a socket to `127.0.0.1:<port>` (0 = a port the OS picks) and returns it; `sock.getsockname()[1]` is the port. The token is `secrets.token_urlsafe(32)` unless `--token` was given.
4. **Database.** `open_db()`:
   - builds `DB(config.db_path(), config.device_id())`. The constructor opens the connection, sets the pragmas, and calls `migrate(fresh)`.
   - `migrate` finds migration files with a number above `PRAGMA user_version`. If there are any and the database already had a version above 0, it first writes `data/backups/readhold-pre-migration-v<old>-to-v<new>.db`. Then it applies each file in its own transaction and sets `user_version`.
   - `open_db` then calls `daily_backup()`. A failure here is logged and ignored.
5. **App.** `create_app(db, token, {"127.0.0.1:<port>", "localhost:<port>"})`. The set is the list of accepted `Host` headers.
6. **Server.** A `uvicorn.Server` on host `127.0.0.1`, `log_level="warning"`, no access log, `log_config=None`. It runs in a daemon thread as `server.run(sockets=[sock])`: uvicorn serves the socket bound in step 3 and binds nothing itself, so the port is never free between the two (before milestone 4.5 a `free_port()` found a port, let it go, and uvicorn bound it again; another program could have taken it in between and been sent the address with the token). `main` polls `server.started` up to 200 times at 20 ms (about 4 s) and then carries on either way.
7. **Backup thread.** A daemon thread named `daily-backup` sleeps one hour, calls `db.daily_backup()`, and repeats. This makes the daily backup happen when the app stays open past midnight.
8. **Show it.** The sign-in address is `http://127.0.0.1:<port>/auth?token=<token>`.
   - `--serve`: print the address and wait on the server thread.
   - `--browser`: `webbrowser.open(url)` and wait.
   - default: import `webview` (pywebview). If the import fails, fall back to the browser. Otherwise `webview.create_window("Readhold", url, width=1360, height=880, min_size=(900, 600), text_select=True)`, hook `winicon.apply(window)` to the window's `shown` event, and call `webview.start(private_mode=False)`.
9. **Stop.** `KeyboardInterrupt` is swallowed. The `finally` block sets `server.should_exit = True`.

### `__main__.py`

| Function | What it does |
|---|---|
| `bind(port: int = 0) -> socket.socket` | A TCP socket bound to `127.0.0.1:<port>` (0 = any free port), not yet listening; uvicorn listens on it. Since milestone 4.5 (finding I5). `__main__.py` is the only module that may import `socket` and `webbrowser` (`tests/test_no_network.py`, `LOW_LEVEL`) |
| `main(argv: list[str] \| None = None) -> int` | The whole sequence above; returns 0 |

### `winicon.py`

pywebview takes an icon only on Linux. On Windows the window would show Python's icon, so this module sets it by hand.

| Name | What it is |
|---|---|
| `ICON` | `PROJECT_ROOT / "assets" / "readhold.ico"` |
| `apply(window) -> None` | Does nothing unless `sys.platform == "win32"` and `ICON` exists. Loads the icon at the system's small and big icon sizes with `LoadImageW` and sends `WM_SETICON` for each. Any exception is logged and ignored |
| `_hwnd(window) -> int` | The window handle: `window.native.Handle.ToInt64()` if present, else `FindWindowW(None, window.title)` |

---

## 2. `config.py`: paths and limits

Everything lives under `READHOLD_HOME` (default: the project folder). `home()` reads the environment variable on every call, which is what lets tests point it at a temporary folder.

| Name | Value / behaviour |
|---|---|
| `PROJECT_ROOT` | Parent of the `readhold/` package |
| `WEB_DIR` | `PROJECT_ROOT/web/static` (always the project's, not under `READHOLD_HOME`) |
| `THEMES_DIR` | `PROJECT_ROOT/themes` |
| `MAX_FILE_BYTES` | `50 * 1024 * 1024`. The largest file that can be imported: a document (`/api/import/file`) or a lecture upload |
| `home() -> Path` | `READHOLD_HOME` or `PROJECT_ROOT` |
| `data_dir()` | `<home>/data`, created if missing |
| `library_dir()` | `<home>/library`, created if missing |
| `backups_dir()` | `<home>/data/backups`, created if missing |
| `exports_dir()` | `<home>/data/exports`, created if missing |
| `db_path()` | `<home>/data/readhold.db` |
| `device_id() -> str` | Reads `data/device.json` (`{"device_id": ...}`). If missing or unreadable, makes a new `uuid4().hex` and writes the file |
| `setup_logging()` | Root logger at INFO; one `RotatingFileHandler` on `data/logs/readhold.log`, 2,000,000 bytes, 3 old files kept. Adds the handler only if no `RotatingFileHandler` is there yet. The handler's formatter is `redact.RedactingFormatter`: the finished line, traceback included, goes through `redact.clean` before it is written, so an API key, a token or a password never reaches the file. The loggers `httpx` and `httpcore` are set to WARNING, so the AI adapters' requests are not listed |

---

## 3. `db.py`: storage

### Module-level names

| Name | What it is |
|---|---|
| `MIGRATIONS_DIR` | `readhold/migrations` |
| `KEEP_DAILY_BACKUPS` | `14` |
| `now() -> str` | UTC time, ISO format, millisecond precision (ends in `+00:00`) |
| `new_id() -> str` | `uuid4().hex` (32 lower-case hex characters, no dashes) |
| `open_db(path: Path \| None = None) -> DB` | Builds the `DB`, then tries `daily_backup()` |
| `_split_sql(script) -> list[str]` | Drops lines that start with `--`, then splits on `;` |

### `class DB`

One SQLite connection, shared by all threads, guarded by `self.lock` (a `threading.RLock`). The connection is opened with `check_same_thread=False` and `isolation_level=None` (autocommit; transactions are explicit). Rows come back as `sqlite3.Row` and the helpers turn them into dicts.

Pragmas set in `__init__`: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`.

| Method | What it does |
|---|---|
| `__init__(path: Path, device: str)` | Opens the file, sets pragmas, runs `migrate(fresh)` where `fresh` means the file did not exist |
| `migrations() -> list[tuple[int, Path]]` | Every `*.sql` in `MIGRATIONS_DIR`, sorted by name; the number is the part before the first `_` |
| `version() -> int` | `PRAGMA user_version` |
| `migrate(fresh: bool)` | See start-up step 4. Each file: `BEGIN`, every statement, `PRAGMA user_version=<n>`, `COMMIT`; on error `ROLLBACK` and re-raise |
| `backup(label: str) -> Path` | Copies the live database to `data/backups/readhold-<label>.db` with SQLite's backup API, holding the lock |
| `daily_backup() -> Path \| None` | Makes `readhold-daily-<local date>.db` if it is not there. Then deletes all but the newest 14 `readhold-daily-*.db` files (sorted by name). Returns the new path, or `None` if today's already existed |
| `all(sql, params=()) -> list[dict]` | All rows |
| `one(sql, params=()) -> dict \| None` | First row |
| `scalar(sql, params=()) -> Any` | First column of the first row, or `None` |
| `execute(sql, params=()) -> int` | Runs a statement; returns `rowcount` |
| `insert(table: str, row: dict) -> dict` | Adds `id` (unless given), and `device_id`, `created_at`, `updated_at` by `setdefault`. Returns the row it inserted. It does not set `deleted`; the column default does |
| `update(table: str, row_id: str, fields: dict) -> int` | Sets the fields plus `updated_at` and `device_id`. Returns `rowcount`. Empty `fields` returns 0 without touching the row |
| `soft_delete(table, row_id) -> int` | `update(..., {"deleted": 1})` |
| `transaction()` | Returns a `_Tx` context manager: takes the lock, runs `BEGIN`, and on exit runs `COMMIT` or `ROLLBACK`. Yields the `DB` |

Things to know:

- Table and column names are put into the SQL text by `insert` and `update`. Values are bound. Callers pass keys that come from pydantic models, never from free-form request data.
- `_Tx` cannot nest: a second `BEGIN` on the same connection raises. Calls to `db.insert`, `db.update` or `db.conn.execute` inside the `with` block join the open transaction.
- `insert` cannot be used for the `settings` table, which has no `created_at` column. `server.py` writes settings with raw SQL.
- Only manual backups (`/api/backup`), pre-migration backups and daily backups exist. Only the daily ones are pruned.

---

## 4. `server.py`: the app, the guard, settings

### 4.1 `create_app(db: DB, token: str, allowed_hosts: set[str]) -> FastAPI`

Builds a `FastAPI` app with the docs, ReDoc and OpenAPI addresses turned off. Every route is a closure inside this function, so each one sees `db` and `token`. In order, it:

1. adds the `guard` middleware, and two exception handlers: `invalid_request` for `RequestValidationError` (section 4.2b) and `preview_needed` for `ai.privacy.PreviewNeeded` (the send preview, 428),
2. defines `/auth` and `/`,
3. mounts `/static` on `config.WEB_DIR` and `/themes` on `config.THEMES_DIR`,
4. defines the reader's routes,
5. calls `register(app, db)` on `compass`, `growth`, `lectures`, `journal`, `timer`, `planner`, `pages`, `search`, `related`, `hub`, `think`, `passages`, in that order. `passages.register` first runs `ensure_index(db)`, which indexes the documents that have no rows in `section_fts` yet,
6. defines sessions, stats, settings, themes, ambience, export, backup and `/favicon.ico` (which answers 204).

Helpers inside `create_app`:

| Helper | What it does |
|---|---|
| `settings_dict() -> dict` | `DEFAULT_SETTINGS` overlaid with every row in `settings` (value parsed as JSON; rows that fail to parse are skipped) |
| `need_doc(doc_id) -> dict` | The document row where `deleted=0`, else HTTP 404 "document not found" |
| `sentence_text(doc_id, a, b) -> str` | Text of sentences with `ord` from `a` to `b`, joined by spaces |
| `_import_result(fn, *args)` | Calls an importer with `db` first; turns `ImportFailed` into HTTP 422 with the message. Then runs `ai.guard.flag_document(db, id)` on the new document, inside a `try`, and puts the sorted flags into the result as `flags`. If that look fails, the failure is logged and `flags` is `[]`: the document is saved, and the next start looks again |
| `_term_card(t: dict)` | Makes, updates or removes the review card for a term (see section 7.2) |

### 4.2 The `guard` middleware

Runs on every request, including static files.

1. **Host.** If the `Host` header is not in `allowed_hosts`: 403 `{"detail": "bad host"}`. This blocks DNS-rebinding.
2. **Token.** For every path except `/auth`: take the `readhold_session` cookie (constant `COOKIE`) or, if absent, the `x-readhold-token` header. Compare with `secrets.compare_digest`. On mismatch: 401 `{"detail": "missing session token"}`.
3. **Writes only from the app's own page** (milestone 4.5, finding L2). For any method but `GET`, `HEAD` and `OPTIONS`: when an `Origin` header is there and is not `<scheme>://<Host>` of this request, or a `Sec-Fetch-Site` header is there and is not `same-origin` or `none`: 403 `{"detail": "a write from another page"}`. Another page on this computer, on another port, is the same "site" to a browser, so `SameSite=Strict` alone would let it send the cookie; this rule stops it. `Origin: null` is refused too. A request with neither header (a script with the token, the test client) passes. All three refusals are built by the inner helper `refuse(status, detail)`.
4. **The send-preview approval** (milestone 4.4). `ai.privacy.approve(request.headers.get("x-ai-approve"))`: a valid one-time token becomes this request's approval (chapter 3, section 7b, *Privacy controls*). Without the header nothing happens.
5. **Run the route.** An exception that reaches the middleware is logged with its path and answered with 500 `{"detail": "Internal error (see data/logs/readhold.log)"}`.
6. **Headers on the response:**

| Header | Value |
|---|---|
| `Content-Security-Policy` | `lectures.SANDBOX_CSP` if the path starts with `/api/lectures/` and ends with `/content.html`; otherwise `CSP` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `Cache-Control` | `no-store`, unless the route set its own value (`setdefault`). The asset route does, so its long cache time is kept |
| `Cross-Origin-Opener-Policy` | `same-origin` (since 4.5, finding I6): no other page that opens this one keeps a handle on it |
| `Cross-Origin-Resource-Policy` | `same-origin`: no other site may embed what this server serves |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` |

The 403 and 401 answers return before step 6, but `refuse` puts four of these headers on them: `CSP`, `nosniff`, `no-referrer` and `no-store` (not the three of 4.5). The 500 answer goes through step 6 like any other response.

### 4.2b The two exception handlers

| Handler | For | Answer |
|---|---|---|
| `invalid_request` | `RequestValidationError` (a body or query that fails its pydantic model) | 422 `{"detail": [{type, loc, msg}, …]}`. FastAPI's own answer also holds `input` (what was sent) and `ctx`; they are dropped, so a refused request never echoes a key or a document back (milestone 4.5, finding I2) |
| `preview_needed` | `ai.privacy.PreviewNeeded`, raised by `privacy.gate` before a call that leaves this computer when "Show what will be sent" is on | 428 `{"detail": "Approve what will be sent to the cloud model.", "preview": {token, task, provider, system, user, note}}`. Nothing was sent. The page shows the text and sends the same request again with `X-AI-Approve: <token>` |

An `HTTPException(422, "<sentence>")` raised by a route is not a `RequestValidationError`: it keeps its sentence as `detail`.

The `CSP` constant:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; frame-src 'self';
frame-ancestors 'none'; base-uri 'none'; form-action 'self'
```

### 4.3 `/auth`

`GET /auth?token=...`. If the token matches (constant-time compare), it answers 303 to `/` and sets the cookie `readhold_session=<token>` with `httponly`, `samesite=strict`, `path=/`. Otherwise 401 "bad token". The cookie has no expiry set, and the token changes on every start unless `--token` is used.

### 4.4 Settings store

Settings are rows in `settings` (`key`, JSON `value`). `GET /api/settings` returns `settings_dict()`. `PUT /api/settings` takes any JSON object, ignores keys that are not in `DEFAULT_SETTINGS`, and upserts each remaining key with `json.dumps(value)`, a new `updated_at`, the device id, and `deleted=0`. Values are not type-checked, with two exceptions, both run before anything is stored, so a refusal changes nothing:

1. **No key in any setting** (milestone 4.5, finding I1). Every string value of the body, of any key (known or not), goes through `redact.looks_like_key`; a key-shaped one answers 422 "`<key>`: that looks like an API key. Save it with the API key field in Settings → AI instead." The value is not repeated. Only top-level string values are looked at: a string inside an object value (`comfort_by_type`) is not.
2. Every `ai_…` key is checked by `ai.settings.check` (chapter 3, section 7b); if one fails the whole request answers 422.

After a request that held an `ai_…` key, `port.settings_changed()` runs (switching AI off, or between local and cloud, cancels the calls that are running) and then `ai.log.purge(db)`, so a shorter `ai_log_days` deletes the older log rows at once. It returns the full settings.

`DEFAULT_SETTINGS`:

| Key | Default | Meaning (from the code comments where given) |
|---|---|---|
| `wpm` | `250` | Pacer speed, words per minute |
| `comfort_wpm` | `250` | Comfortable speed (used by the front end) |
| `pacer_mode` | `"sentence"` | `sentence`, `word` or `focus` |
| `energy` | `"medium"` | Current energy mode |
| `theme` | `"clean"` | Theme folder id (Sand until 2026-11-27) |
| `intensity` | `"gentle"` | `off`, `still`, `gentle`, `lively`; reduce-motion always means still |
| `glass` | `"balanced"` | `solid`, `balanced`, `clear`: how much of the theme shows through panels |
| `sound` | `False` | Ambient sound, off until turned on |
| `sound_volume` | `0.35` | Ambient sound volume |
| `journal_blur` | `False` | Blur journal text until pointed at |
| `notebook_width` | `0` | Lecture notebook width in px; 0 = automatic |
| `note_scale` | `1.0` | Lecture notebook text size |
| `timer_sound` | `True` | A soft chime when a timer ends |
| `timer_rhythm` | `False` | Offer a short break after each focus run |
| `dark` | `"auto"` | `auto`, `light`, `dark` |
| `font` | `"atkinson"` | Reading font |
| `font_size` | `20` | Reading font size |
| `line_width` | `66` | Reading line width |
| `line_height` | `1.7` | Reading line height |
| `tts_voice` | `""` | Read-aloud voice |
| `tts_rate` | `1.0` | Read-aloud rate |
| `review_cap` | `30` | Most cards offered per day (the only setting the server itself reads) |
| `simple_mode` | `False` | Fewer cards on the Overview and a shorter menu |
| `reader_panels_hidden` | `False` | The reader's map and side panel are folded away (Hide panels or Ctrl+\\ in the reader) |
| `nav_hidden` | `False` | The side menu is hidden (« in the menu, ☰ Menu or Ctrl+\\ to bring it back) |
| `prediction_prompts` | `True` | Ask for a prediction before a section |
| `skip_background` | `True` | Skip background sections |
| `clean_view` | `True` | Hide sections marked hidden |
| `speed_ramp` | `True` | Pacer speed ramp |
| `comfort_by_type` | `{}` | Comfortable speed per document type |
| `ai_mode` | `"off"` | `off`, `local` or `cloud`. `off` is the kill switch of all AI |
| `ai_local_api` | `"ollama"` | `ollama` or `openai` (an OpenAI-compatible local server) |
| `ai_local_endpoint` | `"http://localhost:11434"` | The local model server |
| `ai_local_model`, `ai_local_small_model` | `""` | Model names on the local server; an empty small model means the main one |
| `ai_cloud_provider` | `"anthropic"` | `anthropic` or `openai` |
| `ai_cloud_model`, `ai_cloud_small_model` | `""` | Empty means the provider's default (`adapters.CLOUD_DEFAULTS`) |
| `ai_timeout_s` | `60` | Seconds before a call is stopped (5 to 600) |
| `ai_budget_local`, `ai_budget_cloud` | `2000000`, `200000` | Tokens a day per provider; 0 means no limit |
| `ai_preview` | `False` | Milestone 4.4: show what will be sent before a call that leaves this computer, and send it only when approved |
| `ai_log_days` | `30` | Milestone 4.4: how long the AI log keeps its rows: 1, 7 or 30 days |
| `ai_cloud_only_tagged` | `False` | Milestone 4.4: a cloud model gets only documents and notes tagged `#cloud` |

The `ai_…` keys are written twice on purpose: in `DEFAULT_SETTINGS` and in `ai.settings.DEFAULTS`. An `assert` under `DEFAULT_SETTINGS` fails at import if the two differ. An API key is never a setting.

Where no comment exists in `server.py`, the meaning above is read from the key name; the behaviour is in the front end.

### 4.5 Request bodies: `bodies.py`

Each route's JSON body is a pydantic model defined at the top of `server.py`. Most extend `BaseModel`. The ones with a required text extend `Body` from `bodies.py`: in this file `QuestionIn`, `NoteIn`, `TermIn` and `IdeaIn`. The feature modules use `Body` for their own models.

| Name | What it does |
|---|---|
| `Body(BaseModel)` | Adds one check after pydantic's own (`_no_blank_text`). For every field that is declared with a `min_length` and holds a string: if the string is empty after `strip()`, it raises `ValueError("<field> is empty")`, which FastAPI answers with 422 |

`min_length=1` alone lets `"   "` through. `Body` closes that gap. It does not change the text: nothing is trimmed there, so a route that wants a trimmed value still calls `strip()` itself. A field without `min_length`, or one that is `None`, is not checked.

---

## 5. Route table (`server.py`)

All `/api/...` routes need the session token. "404 if missing" means the route checks; where it says "no check", a wrong id is silently accepted. In `QuestionIn`, `NoteIn`, `TermIn` and `IdeaIn`, a text marked "1 to N" that holds only spaces answers 422 (section 4.5).

### 5.1 Shell

| Method | Path | Returns |
|---|---|---|
| GET | `/auth?token=` | 303 to `/` with the cookie, or 401 |
| GET | `/` | `web/static/index.html` |
| GET | `/static/...` | Files under `web/static` |
| GET | `/themes/...` | Files under `themes/` |
| GET | `/favicon.ico` | 204 |

### 5.2 Home, queue, import

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| GET | `/api/home` | | `services.home(db, review_cap)` (section 7.6) |
| GET | `/api/documents` | | `services.queue(db)`: the reading queue with progress, `flags` and `tags` |
| POST | `/api/import/file` | multipart: `file`, `why` (form field, default `""`) | Reads at most 50 MB + 1 byte; 413 if larger. Runs `import_bytes` in a worker thread. Accepts `.pdf`, the text extensions, the code extensions in `CODE_EXT` and files with no extension (section 9.2). Returns `save_parsed`'s result plus `flags` |
| POST | `/api/import/text` | `TextIn`: `title=""`, `text` (max 5,000,000), `format` (`markdown` or `text`, default `markdown`), `why=""` | `import_text`; the same result |

Both imports answer 422 with a readable message on `ImportFailed`. The success shape is:

```json
{"id": "...", "title": "...", "warning": null, "sentences": 42, "sections": 6, "flags": []}
```

`flags` is a list with none, one or both of `hidden_text` and `instructions` (see `documents.flags` in section 6). It is filled after the document is saved: the flags never stop or change an import. When the look itself fails, `flags` is an empty list and the import still answers 200. The Documents tab does not read `flags` from this answer; it reloads the queue.

### 5.3 Documents

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| GET | `/api/documents/{doc_id}?touch=true` | | `store.load_document`; 404 if missing or deleted. With `touch` true, a `queued` document becomes `reading`. The structure view passes `touch=false` |
| GET | `/api/documents/{doc_id}/assets/{name}` | | A cropped equation PNG. `doc_id` must match `[0-9a-f]{32}` and `name` `[0-9a-f]{32}\.png`; the name must be the `asset` of a non-deleted paragraph of that document and the file must exist. Otherwise 404. Sent with `Cache-Control: private, max-age=31536000, immutable`, which the guard leaves in place |
| PATCH | `/api/documents/{doc_id}` | `DocPatch`: `title`, `why`, `deadline`, `status` (`queued`/`reading`/`finished`), `current_pass` (1 to 3), `explain_text`, `quest_question_id` (`""` unlinks), `critique` (max 20000), `reproduce` (max 2000); all optional | Updates the given fields. `status="finished"` also sets `finished_at`. Returns the document row |
| DELETE | `/api/documents/{doc_id}` | | Soft delete, then `passages.reindex`, which removes the document's rows from the search index, then `ai.results.forget_document`, which soft-deletes what an AI feature kept about it (`ai_results`; chapter 3, section 7b). `{"ok": true}` |
| POST | `/api/documents/{doc_id}/restore` | | Sets `deleted=0`; 404 if the id never existed. Returns the row. Calls `passages.reindex`, so search finds it again. The kept AI results are not brought back; the next ask makes new ones |
| POST | `/api/documents/{doc_id}/position` | `PositionIn`: `position` (>= 0) | Saves the resume sentence. No existence check |
| POST | `/api/documents/{doc_id}/read` | `ReadIn`: `ords` (list of int, max 5000) | Sets `read_at` on those sentences where it is still null. No existence check |
| POST | `/api/documents/{doc_id}/slow` | `SlowIn`: `ord`, `signal` (-1 to 1) | Updates `sentences.personal`: `clamp(old * 0.6 + signal * 0.4, -0.3, 0.6)`, rounded to 3 places |
| GET | `/api/documents/{doc_id}/annotations` | | `{questions, highlights, notes, terms, acronyms}`. Each question carries `paragraphs`: the ids linked to it. `acronyms` comes from `find_acronyms` |
| GET | `/api/documents/{doc_id}/define?term=` | | `{in_document, acronym, glossary}`: `find_definitions` hits, the acronym expansion (also tried without a trailing `s`), and glossary rows with the same term (case-insensitive) that have a definition, from any document |
| GET | `/api/templates?kind=other` | | A list of question templates for a section kind |
| GET | `/api/documents/{doc_id}/summary` | | `services.summary` (section 7.4) |
| POST | `/api/documents/{doc_id}/export` | | Writes the Markdown file. `{"path": ..., "markdown": ...}` |

Two more routes on documents are defined in `passages.py` (chapter 3, section 4b):

| Method | Path | Returns |
|---|---|---|
| GET | `/api/passages?q=&document_id=` | `{results}`: the sections that hold the words, best first, from the full-text index. Each has `document_id`, `document_title`, `section_id`, `section_title`, `sentence` (the ord to open the reader at), `snippet`, `score`. With `document_id`, only that document; 404 if it is not a non-deleted document |
| GET | `/api/documents/{doc_id}/last-session` | `{session}`: the last finished session of the document, or `null`. 404 if the document is missing or deleted. No page calls it |

And two in `ai/resume.py` (chapter 3, section 7b), the Resume briefing:

| Method | Path | Returns |
|---|---|---|
| GET | `/api/documents/{doc_id}/resume` | `{session, here, ai: {mode}, brief}`: the facts of the last finished reading session, where the reader is now, whether AI is on, and the kept recap or `null`. No model is called. 404 if the document is missing or deleted |
| POST | `/api/documents/{doc_id}/resume/brief` | Body `{fresh?}`. `{brief}`: the recap, kept or newly asked of the model. 404, 409 (no finished session, AI off or not set up, budget used up, a refused file, a call stopped by the off switch), 504 (the model took too long) or 502 (the model failed). With AI off it is 409 also when a recap is kept |

And three for Organize (milestone 3.3; chapter 3, sections 7c and 7b): `GET /api/organize/{doc_id}` and `PUT /api/documents/{doc_id}/tags` in `readhold/organize.py` (the document's tags, related documents, suggested tags; setting the tags, with `expect`), and `POST /api/documents/{doc_id}/organize/suggest` in `ai/organize.py` (a model's suggestion, with AI on). Other AI routes on a document (explain, digest, ask, study notes) are in chapter 3, section 7b too.

### 5.4 Fix structure

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| PATCH | `/api/sections/{sec_id}` | `SectionPatch`: `title`, `kind`, `background`, `hidden`, `prediction`, `prediction_check`; all optional | Updates; booleans are stored as 0/1. 404 if no row changed. `kind` is not checked against the known kinds. When `title` is sent, `passages.reindex` runs for the section's document |
| POST | `/api/sections/{sec_id}/merge-up` | | Moves this section's paragraphs to the previous non-deleted section and soft-deletes this one, in one transaction; then `passages.reindex`. 400 "This is the first section." if there is none before |
| POST | `/api/paragraphs/{par_id}/split` | `SplitIn`: `title="New section"` | Starts a new section at this paragraph: bumps `ord` of later sections, inserts a section right after with `kind = section_kind(title)`, the same `level`, and `background`/`hidden` set from the kind; moves this paragraph and the later ones of the old section into it; then `passages.reindex`. Returns `{"id": new_section_id}` |

### 5.5 Questions

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| POST | `/api/questions` | `QuestionIn`: `document_id`, `text` (1 to 500), `section_id`, `source_sentence`, `section_kind` (optional) | Inserts with `ord` = number of existing questions. If `section_kind` is given, calls `services.learn_template`. Returns the row plus `paragraphs: []` |
| PATCH | `/api/questions/{q_id}` | `QuestionPatch`: `text`, `answer` | Setting `answer` sets `answered_at` (or clears it when the answer is blank). If the question now has a non-blank answer, **upserts a `question` card**: front = question text, back = answer, plus `"\n\nFrom the text: <sentence>"` when `source_sentence` is set. If `answer` was sent and the question now has no answer, **the card is removed**. 404 if missing |
| DELETE | `/api/questions/{q_id}` | | Soft delete; removes its card |
| POST | `/api/questions/{q_id}/link` | `LinkIn`: `paragraph_id` | Toggles "this paragraph answers the question". Returns `{"linked": bool}` |

### 5.6 Highlights and margin notes

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| POST | `/api/highlights` | `HighlightIn`: `document_id`, `sentence`, `end_sentence` (defaults to `sentence`), `type` (`claim`/`evidence`/`definition`/`confusing`/`idea`), `note=""` | Stores the highlight with `text` copied from the sentences. Calls `sync_highlight_card` (a `definition` highlight **creates a card**). An `idea` highlight **also inserts a row in `ideas`** with the note, or the text if there is no note |
| PATCH | `/api/highlights/{h_id}` | `HighlightPatch`: `note`, `cloze`, `resolved`, `type` | Updates, then `sync_highlight_card`. Setting `cloze` on an `evidence` highlight **creates a `cloze` card**. Changing `type` **removes the card of the old type**. 404 if missing |
| DELETE | `/api/highlights/{h_id}` | | Soft delete; removes its `definition` and `cloze` cards |
| POST | `/api/notes` | `NoteIn`: `document_id`, `sentence`, `text` (1 to 5000) | Inserts and returns the note. `origin` is not in the body, so a note made here has the empty default: the reader wrote it |
| PATCH | `/api/notes/{n_id}` | `NotePatch`: `text` | Sets `text` and, **when the text really changes, empties `origin`**: once the reader edits a note a model wrote, it is theirs. Saving the same text again keeps `origin`. `{"ok": true}` |
| DELETE | `/api/notes/{n_id}` | | Soft delete |

These `notes` are margin notes on a sentence. The Notes page in the app is the `pages` table, in another module. One more route writes this table: `POST /api/ai/results/{result_id}/note` in `ai/explain.py` saves an AI explanation as a margin note with `origin='ai'` (chapter 3, section 7b).

### 5.7 Terms (Glossary in the app)

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| GET | `/api/terms` | | Non-deleted terms where `is_concept=0` or a definition exists, with `document_title`, sorted by term |
| POST | `/api/terms` | `TermIn`: `term` (1 to 200), `guess=""`, `definition=""`, `document_id`, `sentence`, `source_text=""` | Inserts; `_term_card` **creates a `term` card** if there is a definition or a guess |
| PATCH | `/api/terms/{t_id}` | `TermPatch`: `guess`, `definition`, `is_concept` | Updates; `_term_card` again. 404 if missing |
| DELETE | `/api/terms/{t_id}` | | Soft delete; removes its card |
| GET | `/api/concepts?term=` | | The concept page: `{term, glossary, highlights (max 100), notes (max 100), mentions (max 60)}` across all non-deleted documents. Matching is `LIKE '%term%'` with `%`, `_` and `\` escaped so they are literal |

### 5.8 Review, cards, tab counts

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| GET | `/api/review/due` | | `{cards, due_total, cap_left}` |
| POST | `/api/review/{card_id}` | `RatingIn`: `rating` (1 to 4) | Reschedules the card and **inserts a `reviews` row**. Returns `{id, due}`. 404 if missing or deleted (since 5.1: a card you deleted is not rated) |
| GET | `/api/cards?document_id=` | | That document's cards by `created_at`; without the parameter, up to 500 cards by `due` |
| GET | `/api/library/counts` | | `{documents, lectures, goals, review_due, terms}` for the Study tabs. `review_due` is `min(due_total, cap_left)` |
| GET | `/api/plan/counts` | | `{tasks_now}`: open `todos` due today or earlier |
| GET | `/api/notes/counts` | | `{notes, ideas, think}`: `pages`, `ideas`, and new `suggestions` plus today's new `daily_picks` |

The three count routes read tables owned by other modules (`lectures`, `quests`, `todos`, `pages`, `suggestions`, `daily_picks`).

### 5.9 Ideas, sessions, stats

| Method | Path | Body | Returns and side effects |
|---|---|---|---|
| GET | `/api/ideas` | | Ideas with `document_title`, newest first |
| POST | `/api/ideas` | `IdeaIn`: `text` (1 to 5000), `document_id`, `sentence` | Inserts and returns the idea |
| DELETE | `/api/ideas/{i_id}` | | Soft delete |
| POST | `/api/sessions` | `SessionIn`: `document_id`, `energy` (`low`/`medium`/`high`, default `medium`), `time_box_min` (1 to 240, default 15), `question=""`, `quest_id`, `step_id` | Inserts with `started_at = now()`. With a `document_id`, `start_ord` and `last_ord` are both set to the document's `position`: the sentence the session starts at. Returns the row |
| PATCH | `/api/sessions/{s_id}` | `SessionPatch`: `focused_ms`, `longest_run_ms`, `distractions`, `sentences_read`, `next_step`, `output` (max 5000), `time_box_min` (1 to 240), `feel` (`energized`/`neutral`/`drained`/`""`), `ended=false` | Updates. `ended: true` sets `ended_at`. When the session has a document, every call also sets `last_ord` to the document's `position` at that moment, so the last save holds where the session stopped. `{"ok": true}` |
| GET | `/api/stats` | | `{days: daily_stats(28), streak, week: weekly_review()}` |

### 5.10 Settings, themes, export

| Method | Path | Returns and side effects |
|---|---|---|
| GET | `/api/settings` | All settings |
| PUT | `/api/settings` | Saves known keys; returns all settings. 422 for a key-shaped string in any setting, or an `ai_…` value that fails its check (section 4.4) |
| GET | `/api/themes` | Each `themes/*/theme.json` plus `id` (folder name) and `has_scene`. A file that is not valid JSON is logged and skipped |
| GET | `/api/ambience` | `{reviews_today, energy_today}` for the animated themes. `energy_today` comes from `compass.checkin_today` |
| POST | `/api/export/all` | Writes the JSON export and a folder of Markdown sheets. `{"path": json_path}` |
| POST | `/api/backup` | `db.backup("manual-<YYYYmmdd-HHMMSS>")`. `{"path": ...}` |

---

## 6. Data model: the reader tables

Defined in `0001_init.sql`, with columns added by `0002`, `0003`, `0005`, `0008`, `0015`, `0017`, `0019` and `0021`. Every table except `settings` (before `0005`) has the sync columns:

| Column | Meaning |
|---|---|
| `id` | UUID as 32 hex characters, primary key |
| `device_id` | The device that last wrote the row |
| `created_at`, `updated_at` | UTC ISO strings |
| `deleted` | 0 or 1. Rows are never removed |

The tables below list only the other columns.

### `documents`

| Column | Meaning |
|---|---|
| `title` | Shown title (cut to 300 characters on import) |
| `source` | The original file name, or `"pasted"`. A document imported from a link by an earlier version holds the link |
| `source_type` | `markdown`, `text`, `pdf` or `plain` (the fallback). Documents imported from a link by an earlier version keep `web` or `arxiv`; nothing writes those values now |
| `file_hash` | SHA-256 of the original; the file is `library/<hash><ext>` |
| `why` | "Why am I reading this?" |
| `deadline` | Optional date text |
| `status` | `queued`, `reading`, `finished` |
| `import_warning` | Why the import fell back, or null |
| `position` | Sentence `ord` of the resume point |
| `current_pass` | Reading pass, 1 to 3 |
| `explain_text` | "In my words" text |
| `total_sentences` | Count of all sentence rows made at import (paced or not) |
| `finished_at` | Set when status becomes `finished` |
| `quest_question_id` (0003) | The goal question this document is read for; no foreign key |
| `critique` (0005) | Strengths, weaknesses, what to test |
| `reproduce` (0005) | One result to reproduce |
| `import_flags` (0017) | What the importer found odd about the file itself: words with a space between them. `NOT NULL`, default `''`. The only word today is `hidden_text`, set by the PDF importer (section 9.3) and by `import_bytes` when a PDF falls back to plain text and holds text (section 9.1). Written once, by `save_parsed` |
| `flags` (0017) | `import_flags` plus what `ai.guard.flag_document` found in the text: `instructions` = text that reads like orders to an AI model. Words in alphabetical order with a space between them. **NULL means the document has not been looked at yet**; an empty string means it was looked at and nothing was found. Written only by `flag_document` (after an import, and at start for rows that are still NULL), without a change to `updated_at`. It is the "flagged text" mark on the Documents tab |
| `tags` (0021) | The reader's tags on the document (milestone 3.3): words with a space between them, lower case, each as `organize.clean_tag` writes it (a letter first, then letters, digits, `-` or `_`, at most 40 characters), at most 12. `NOT NULL`, default `''`. Written only by `organize.set_tags` (`PUT /api/documents/{doc_id}/tags`); a model may suggest a tag, but only the reader adds one. A tag is also a collection: the Documents tab draws a chip per tag from `GET /api/documents`. There is no table of tags or collections |

### `sections`

| Column | Meaning |
|---|---|
| `document_id` | Owner; references `documents(id)` |
| `ord` | Order in the document |
| `title` | Heading text (cut to 300) |
| `kind` | `abstract`, `intro`, `related`, `method`, `results`, `discussion`, `conclusion`, `references`, `appendix`, `other` |
| `level` | Heading depth, 1 to 3 from importers |
| `background` | 1 = safe to skip. Set at import for `related` and `appendix` |
| `hidden` | 1 = hidden by clean view. Set at import for `references` |
| `prediction`, `prediction_check` | The reader's guess before the section and the note afterwards |

Index: `idx_sections_doc(document_id, ord)`.

### `paragraphs`

| Column | Meaning |
|---|---|
| `document_id`, `section_id` | Owners; both are foreign keys |
| `ord` | Order across the whole document, not within the section |
| `kind` | `text`, `list` (paced); `code`, `caption`, `equation`, `reference`, `fragment` (set aside). The SQL comment omits `fragment`, but importers produce it |
| `asset` (0002) | File name in `library/assets/<document id>/`, or `''` |

### `sentences`

| Column | Meaning |
|---|---|
| `document_id`, `paragraph_id` | Owners; foreign keys |
| `ord` | Order across the whole document. Unique per document (`idx_sentences_doc`). Highlights, notes and `position` refer to it, so it must never change |
| `text` | The sentence. For non-paced paragraphs, the whole paragraph as one row |
| `words` | `text.count_words` |
| `density` | 0 to 1 from `density.score`; 0 for non-paced kinds |
| `personal` | Learned adjustment, -0.3 to 0.6, from `/slow` |
| `read_at` | When it was first marked read, or null |

### `questions` and `question_links`

| Column | Meaning |
|---|---|
| `questions.document_id` | Owner; foreign key |
| `questions.section_id` | Optional section; no foreign key |
| `questions.source_sentence` | `ord` of the sentence the question came from |
| `questions.text` | The question |
| `questions.ord` | Order in the list |
| `questions.answer` | The recall answer in the reader's words |
| `questions.answered_at` | Set when a non-blank answer is saved |
| `question_links.question_id`, `.paragraph_id` | "This paragraph answers this question". Foreign keys. Unlinking sets `deleted=1`; linking again clears it |

### `template_bank`

| Column | Meaning |
|---|---|
| `section_kind` | Section kind the question was asked in |
| `text` | The question text |
| `uses` | Times it was asked; starts at 1 |

`UNIQUE(section_kind, text)`.

### `highlights`

| Column | Meaning |
|---|---|
| `document_id` | Owner; foreign key |
| `sentence`, `end_sentence` | First and last sentence `ord` |
| `type` | `claim`, `evidence`, `definition`, `confusing`, `idea` |
| `text` | Copy of the sentence text at the time of highlighting |
| `note` | Optional note. For `definition`, it names the thing defined |
| `cloze` | The word hidden on a fill-in-the-blank card (`evidence` only) |
| `resolved` | For `confusing`: 1 when cleared up |

### `notes` (margin notes)

| Column | Meaning |
|---|---|
| `document_id` | Foreign key to `documents` |
| `sentence` | The `ord` of the sentence the note is on |
| `text` | The note, plain text |
| `origin` (0019) | Who wrote it. `NOT NULL`, default `''` = the reader. `'ai'` = saved from something an AI model wrote (`ai.explain.save_as_note`); the reader shows a label for it. `api_note_patch` sets it back to `''` when an edit changes the text. Nothing else writes it |

### `terms`

| Column | Meaning |
|---|---|
| `term` | The word or phrase |
| `guess` | The reader's guess before looking it up |
| `definition` | The checked definition |
| `document_id`, `sentence` | Where it was met; both optional, no foreign key |
| `source_text` | The sentence it was met in |
| `is_concept` | 1 for a backtick term collected at Markdown import. Hidden from the Glossary until it has a definition |

### `cards` and `reviews`

| Column | Meaning |
|---|---|
| `cards.document_id` | Optional owner |
| `cards.source_type` | `term`, `definition`, `question`, `cloze`; other modules add `lecture_note` (`lectures.py`) and `ai` (a card kept from Study notes, `readhold/ai/notes.py`, with `source_id` `<result id>:<index>`; insert-only, see chapter 3, section 7b) |
| `cards.source_id` | The id of the term, highlight or question |
| `cards.front`, `cards.back` | Card text |
| `cards.fsrs` | The FSRS card state as JSON (`Card.to_dict()`) |
| `cards.due` | UTC ISO string, second precision |
| `cards.suspended` | 1 = never offered. Since milestone 5.1 it means "you deleted this card in Review": `trash.delete` sets it with `deleted=1`, `trash.restore` clears both, and `upsert_card` leaves such a card deleted (section 7b) |
| `reviews.card_id` | Foreign key to `cards` |
| `reviews.rating` | 1 to 4 |
| `reviews.reviewed_at` | UTC ISO string, second precision |

`UNIQUE(source_type, source_id)` on cards: one card per source. A highlight can have two cards because the types differ (`definition` and `cloze`).

### `sessions`

| Column | Meaning |
|---|---|
| `document_id` | Optional document |
| `started_at`, `ended_at` | Start and end |
| `energy` | `low`, `medium`, `high` |
| `time_box_min` | Planned length |
| `question` | The question the session is for |
| `focused_ms`, `longest_run_ms`, `distractions`, `sentences_read` | Counters sent by the front end |
| `next_step` | "Where I pick up next time"; shown on the resume card |
| `quest_id`, `step_id` (0003) | The goal and step this session works on |
| `output` (0003) | What the session produced |
| `feel` (0005) | `energized`, `neutral`, `drained`, or `''` |
| `guess_hard`, `real_hard` (0008) | Kept but unused. They held the 0 to 10 guess and rating of the removed calm tools (chapter 2, section 5); nothing reads or writes them now |
| `start_ord`, `last_ord` (0015) | The sentence `ord` where the session started and where it stopped. Both nullable. Set only by `POST` and `PATCH /api/sessions` for a session with a document (section 5.9). A session made by the timer (`timer.py`) has neither, even when it is linked to a document. Read by `passages.last_session` |

### `ideas`

`text`, optional `document_id` and `sentence`.

### `settings`

`key` (primary key), `value` (JSON text), `updated_at`. Migration `0005` added `id`, `device_id` and `deleted`, and gave existing rows an id. There is no `created_at`.

### `section_fts` (0015)

A full-text index over sections: an FTS5 virtual table with the tokenizer `unicode61 remove_diacritics 2`. One row per section that has at least one sentence. It has no sync columns.

| Column | Meaning |
|---|---|
| `title` | The section title (indexed) |
| `body` | The section's sentences in `ord` order, joined by newlines (indexed) |
| `document_id`, `section_id` | Where the row comes from (`UNINDEXED`) |
| `first_ord` | The `ord` of the section's first sentence (`UNINDEXED`) |

It is derived data. `passages.reindex(db, doc_id)` deletes and rebuilds the rows of one document, and nothing else writes to it. It is not in `EXPORT_TABLES`. SQLite keeps its content in shadow tables named `section_fts_data`, `section_fts_idx`, `section_fts_content`, `section_fts_docsize` and `section_fts_config`.

### Anchors

A place in a document is a document id plus a sentence `ord`, with the section id when a section is meant. `ord` never changes (section 11), and the reader opens at one with `#/read/<document id>?s=<ord>`. `search_sections` and `last_session` return places in this form. The reader itself goes to that sentence only if the pacer visits it; otherwise it goes to the next paced sentence (chapter 5, `isPacedOrNext`).

### Relations

```
documents 1--n sections 1--n paragraphs 1--n sentences
documents 1--n questions n--n paragraphs   (through question_links)
documents 1--n highlights, notes           (by sentence ord)
terms, ideas, sessions, cards  -> documents (optional, not enforced)
cards 1--n reviews
cards.source_id -> terms.id | highlights.id | questions.id  (by source_type)
```

`foreign_keys=ON`, so the declared references are enforced on insert.

---

## 7. `services.py`: domain logic

### 7.1 Question templates

| Name | What it does |
|---|---|
| `DEFAULT_TEMPLATES` | Built-in questions per section kind. `appendix` and `references` have none |
| `question_templates(db, kind) -> list[str]` | The 3 most-used learned templates for the kind, then the defaults (an unknown kind gets the `other` defaults), without duplicates |
| `learn_template(db, kind, text)` | Ignores blank text and text over 140 characters. Bumps `uses` (and clears `deleted`) if the pair exists, else inserts it |

### 7.2 Cards and FSRS

The module creates one `fsrs.Scheduler()` with the library's default settings (`_scheduler`). The pinned version is `fsrs==5.1.3`.

| Function | What it does |
|---|---|
| `upsert_card(db, source_type, source_id, front, back, document_id) -> dict` | If a card exists for the source (deleted or not): update `front` and `back`, and set `deleted=0` unless the card is `suspended` (you deleted it in Review: it stays deleted, and only Undo brings it back; since 5.1). The FSRS state and due date are kept. Otherwise insert a new card with a fresh `Card()` state and its due date (due at once) |
| `remove_card(db, source_type, source_id)` | Soft-deletes the card if there is one |
| `reviews_today(db) -> int` | Reviews since local midnight |
| `due_cards(db, cap) -> dict` | `cap_left = max(cap - reviews_today, 0)`. `cards`: non-deleted, non-suspended cards with `due <= now`, oldest due first, at most `cap_left`. `due_total`: the same count without the limit |
| `review_card(db, card_id, rating) -> dict` | Loads the state, runs `_scheduler.review_card(card, Rating(rating))`, saves the new state and due date, inserts a `reviews` row. Raises `KeyError` (404 at the route) if the card id is unknown or, since 5.1, the card is deleted |
| `definition_card_front(sentence, note) -> str` | `"What is <note>?"` if there is a note; else tries to pull the subject out of "X is/are/refers to/denotes/means ..."; else `"Recall the definition: <first six words> …"` |
| `cloze_front(sentence, hidden) -> str` | Replaces the first occurrence of `hidden` with `_____` |
| `sync_highlight_card(db, hl)` | Deleted highlight: remove both cards. `definition`: upsert a `definition` card (front from `definition_card_front`, back = the text); any other type: remove the definition card. `evidence` with `cloze`: upsert a `cloze` card (back = the hidden word, blank line, the full text); anything else (`evidence` without `cloze`, or another type): remove the cloze card |
| `_iso(d) -> str` | UTC ISO string at second precision |

Card rules in one place:

| Source | Card made when | Card removed when |
|---|---|---|
| Question | The question has a non-blank answer after a PATCH | A PATCH clears the answer, or the question is deleted |
| Term | It has a definition, or only a guess (the back then says the guess is not checked yet). `source_text` is appended as "In context: ..." | It has neither, or it is deleted |
| Definition highlight | Created or patched | Its `type` is changed to another one, or the highlight is deleted |
| Evidence highlight | `cloze` is set | `cloze` is cleared, its `type` is changed to another one, or the highlight is deleted |

The daily cap is `review_cap` (default 30). It limits how many cards `due_cards` hands out; `review_card` does not check it.

### 7.3 `EXPORT_TABLES`

The list of tables written by `export_all`. See 7.5.

It includes `ai_results` (migration `0018`, chapter 3, section 7b): the recaps and explanations an AI feature showed you, as long as they are kept (Clear AI history deletes the rows, but not from an export file made before). `ai_log` is left out on purpose, and no other export holds it either: an export file is kept for good, while the AI log is meant to be gone after its 1, 7 or 30 days or on Clear AI history (`tests/test_ai.py` `test_the_ai_log_is_not_in_the_full_export`). Milestone 4.4 had added a separate **Export AI data** (`POST /api/ai/export`) that wrote it; that was removed on 2026-11-26, so this full export is the one export of AI data, and it holds `ai_results`. Clear AI history still deletes any old `readhold-ai-export-*.json` files. `notes` is exported with its `origin` column.

It still names `unstick_events` and `steady_notes`, the two tables of the calm tools that were removed on 2026-11-25 (chapter 2, section 5). Both tables are kept in the database but nothing reads or writes them, so the export carries only rows from before the removal. Still so after Phase 5 (a known limit of 5.1). Every table `trash.py` deletes from is in the list, and the export reads `deleted=0` rows only.

### 7.4 Summary sheet

`summary(db, doc_id) -> dict` builds the sheet from the document's own annotations:

| Key | Content |
|---|---|
| `document` | `id, title, source, why, explain_text, status, critique, reproduce` |
| `claims` | `claim` highlights in sentence order, each with `evidence`: the `evidence` highlights that come after it and before the next claim |
| `orphan_evidence` | Evidence that comes before any claim |
| `questions` | `id, text, answer, source_sentence` |
| `terms` | The document's terms where `is_concept=0` |
| `definitions`, `ideas` | Highlights of those types |
| `confusions` | `confusing` highlights not yet resolved |
| `notes` | Margin notes |
| `predictions` | Sections with a non-empty `prediction` |
| `acronyms` | `find_acronyms` over the document |
| `progress` | `store.key_sentence_stats` |

`summary_markdown(db, doc_id) -> str` turns that into Markdown. Sections appear only when they have content, in this order: title, `Source:`, "Why I read this", `## In my words`, `## Main points`, `## My critique`, `## Predictions`, `## Questions`, `## Glossary`, `## Still confusing`, `## Ideas`, `## Margin notes`. Each quoted sentence gets a marker: `([s12](<source>))` when the source starts with `http`, else `(s12)`. The whole text goes through `text.math_to_markdown`, so formulas come out as `$...$` and `$$...$$`.

`export_markdown_file(db, doc_id) -> str` writes that Markdown to `data/exports/<safe title> (<first 8 characters of the id>).md` and returns the path. The safe title keeps word characters, `-` and spaces, cut to 80 characters, or `document`. Like the full export (7.5), the id keeps two documents with one title apart and a title such as `CON` from being a reserved name.

### 7.5 Full export

`export_all(db) -> str`:

1. For each table in `EXPORT_TABLES`, selects all rows, leaving out `deleted=1` when the table has that column.
2. Writes `data/exports/readhold-export-<stamp>.json`.
3. Makes `data/exports/notes-<stamp>/` and writes one summary Markdown file per non-deleted document, named `<safe title> (<first 8 characters of the id>).md` (since milestone 4.5, finding I3). The safe title is the title's word characters, `-` and spaces, cut to 80 characters, or `document`. The id keeps two documents with one title apart, and a title such as `CON` or `NUL` from being a reserved file name on Windows.
4. Returns the JSON path.

### 7.6 Home, queue, stats

| Function | What it does |
|---|---|
| `home(db, review_cap) -> dict` | `resume`: the document of the most recently updated session (joined to a non-deleted document); if there is none, the most recently updated document that is not finished. It holds `document_id, title, position`, the `sentence` text at that position, `next_step` from that session, and `progress`. Also `confusions` (5 newest unresolved, from non-deleted documents), `due_cards` (`min(due_total, cap_left)`), `streak`, and `today` (the last entry of `daily_stats(14)`) |
| `queue(db) -> list[dict]` | Non-deleted documents, unfinished first, then those with a deadline by date, then by `updated_at` descending. Each has `progress`, `flags` as a list (`documents.flags` split at spaces; NULL and empty both give `[]`) and `tags` as a list (`documents.tags` split at spaces: the reader's tags, also the collections of the Documents tab). `GET /api/documents/{doc_id}` (`store.load_document`) returns the same column as it is stored: a string or null |
| `daily_stats(db, days=14) -> list[dict]` | One entry per local day, oldest first, ending today: `date, focused_ms, longest_run_ms` (the day's maximum), `sentences, reviews, distractions, counts`. A session counts on the local date of its `started_at`. `counts` is true with at least 10 focused minutes or any review |
| `streak(days) -> int` | Counts back from today over days where `counts` is true. Today not counting yet does not break it |
| `weekly_review(db) -> dict` | Last 7 days: `finished` documents, `explained` (up to 20 answered questions), `open_confusions` (up to 20), `logs` (day logs), `steps_done` (steps of live goals only, since 5.1), `quests_done`, `feel` (`energy_feel(28)`), `practice` (counts of `got`/`partly`/`missed`), `habits` (days checked per habit). It reads tables owned by `compass` and `growth` |
| `energy_feel(db, days=28) -> dict` | Groups sessions that have a `feel` by what they were on: the step title, else the document title, else the session's question, else `"Session"`. Returns `drains` and `lifts` (top 5 each) and `total` |
| `_local_date(iso)` | An ISO string to a local date |

---

## 7b. `trash.py`: delete and Undo on every kind of record (milestone 5.1)

Milestone 5.1 of `docs/ai/PLAN.md` ("Delete on everything you upload or generate", no AI): every kind of record the reader makes, and every single AI result, can be removed from the app, with Undo. Most kinds already had their own delete route with Undo (documents, lectures, notes, ideas, highlights, questions, terms, tasks, routines, quest steps); this module adds one route pair for the rest. It imports `fastapi` and `db`, and `growth._creates_cycle` inside `_check_restore`. `server.create_app` calls `trash.register(app, db)` after `passages.register`. The page side is `web/src/trash.ts` (chapter 4).

### Names

| Name | What it is |
|---|---|
| `ID` | 32 hex characters |
| `KINDS` | kind → table: `card` → `cards`, `habit` → `habits`, `quest` → `quests`, `map_edge` → `map_edges`, `journal` → `journal_entries`, `letter` → `letters`, `side_quest` → `side_quests`, `checkin` → `checkins`, `focus` → `timer_runs`, `ai_result` → `ai_results`. The only place a table name comes from; the request names a kind |
| `AI_TARGETS` | `document` → `documents`, `page` → `pages`, `idea` → `ideas`: what an AI result can be about, and must still be there for its restore |

### Functions

| Function | What it does |
|---|---|
| `_row(db, kind, rid) -> (table, row)` | 404 for a kind that is not in `KINDS`, an id that is not `ID`, or no row. The row may be deleted |
| `delete(db, kind, rid)` | 404 when the row is already deleted. 409 "This timer is still running. Stop it first, then delete it." for a `focus` run whose `status` is `active`. Then, in one transaction: `deleted=1` with `updated_at` and `device_id`; a `card` also gets `suspended=1`; a `journal` page also soft-deletes the live `ink` row with `owner_type='journal'` and `owner_id` = its day; a `focus` run also soft-deletes its `sessions` row and, when it has a `todo_id` and is not a break, takes its `elapsed_ms` off the task's `spent_ms` (never below 0). Returns `{ok, kind, id}` |
| `restore(db, kind, rid)` | When the row is deleted: `_check_restore`, then in one transaction `deleted=0`; a `card` gets `suspended=0`; a `journal` page's deleted `ink` row of that day comes back; a `focus` run's session comes back and its `elapsed_ms` is added to the task again; a `quest` whose `status` is `active` is set to `parked` when another live goal is active now. When the row is not deleted: nothing changes (a second Undo is harmless). A `journal` answer also carries `entry`, the page as `GET /api/journal/{day}` gives it (`prompts` parsed). Returns `{ok, kind, id}` |
| `_check_restore(db, kind, row)` | A `card` that is not `suspended` went with its source (a term, a question, a highlight): 404 "This card went with what it came from. Restore that instead." A `map_edge`: 404 "One of its concepts is gone." unless both nodes are live in its goal and the goal is live; 409 "That link is already there." when a live edge joins the same two nodes; 409 "That would make a loop: one of them already needs the other." (`growth._creates_cycle`). An `ai_result` whose `target_type` is in `AI_TARGETS`: 404 "What it was about is no longer here." when that row is deleted. Other target types (`library`, `plan`, `routine`) are not checked |
| `register(app, db)` | The two routes |

### Routes

| Method and path | Returns | Codes |
|---|---|---|
| `DELETE /api/items/{kind}/{rid}` | `{ok, kind, id}` | 404 (kind, id, row, already deleted); 409 (a running focus run) |
| `POST /api/items/{kind}/{rid}/restore` | `{ok, kind, id}` (and `entry` for `journal`) | 404 (kind, id, row; a card that went with its source; an AI result whose target is gone); 409 (a map link that is there again or would loop) |

The old routes still work and are undone by this restore: `DELETE /api/habits/{id}` and `DELETE /api/quests/{id}` soft-delete the same rows.

### The fixes it needed elsewhere

| Where | Fix |
|---|---|
| `services.upsert_card` | A card that exists but is `suspended` (you deleted it in Review) gets its new `front` and `back` and stays deleted; before, every upsert set `deleted=0`. So editing a term or a question no longer brings a deleted card back; only Undo does. An `ai` card is insert-only anyway (`ai/notes.py`) |
| `services.review_card` | Reads the card with `deleted=0`: rating a deleted card is a `KeyError`, 404 at the route |
| `services.weekly_review` | `steps_done` joins the goal with `q.deleted=0` |
| `journal.day_story` | Steps and answers join their goal with `q.deleted=0`; habit checks join their habit with `h.deleted=0`. A deleted session was already left out |
| `compass.checkin_today` | `ORDER BY created_at DESC, rowid DESC`: two check-ins in the same second keep the order they were made in, so removing the latest brings back the one before |
| `timer.py` | New `GET /api/timer/recent` (chapter 3, section 1.4): the finished runs the Timer page can delete |

Exports and stats read `deleted=0` rows only, so a deleted record leaves them too (`test_the_export_leaves_out_what_you_deleted`).

**Limits.** Removing a check-in removes one tap: an earlier check-in of the same day counts again (the energy of the day may change back). A pen stroke saved at the moment of a journal delete could bring that day's drawing back (`PUT /api/ink/journal/<day>` sets `deleted=0` on the one ink row of that day); the page saves the last strokes before it deletes, to keep that from happening. After a journal page is deleted and the day written again, the old drawing stays deleted: the new page starts without it. `EXPORT_TABLES` still lists `unstick_events` and `steady_notes` (7.3).

---

## 8. `store.py`: rows in, document out

| Name | What it does |
|---|---|
| `PACED_KINDS` | `{"text", "list"}`. Only these are split into sentences and scored. Code, equations, captions and references are not |
| `save_parsed(db, doc: ParsedDoc, source: str, file_hash: str \| None, why: str = "") -> dict` | See below |
| `assets_dir(doc_id)` | `library/assets/<doc_id>/` |
| `load_document(db, doc_id) -> dict \| None` | The document row plus `sections`, each with `paragraphs`, each with `sentences` |
| `doc_sentences(db, doc_id) -> list[tuple[int, str]]` | `(ord, text)` for sentences in `text`, `list` and `caption` paragraphs. Feeds the definition and acronym finders |
| `key_sentence_stats(db, doc_id) -> dict` | `{total, read, ratio}` over "key sentences": `text` and `list` paragraphs in sections that are neither `background` nor `hidden` |

### `save_parsed` step by step

1. Make a document id. Walk the sections in order.
2. Per section: `kind = sec.kind or section_kind(sec.title)`; `background = kind in BACKGROUND_KINDS`; `hidden = kind in HIDDEN_KINDS`; title cut to 300.
3. Per paragraph: make an id. If it has an `image`, write it to `library/assets/<doc id>/<paragraph id>.png` and store that file name in `asset`.
4. Sentences: a paced paragraph goes through `split_sentences`, and each sentence gets `density.score`. Any other kind is stored whole as one sentence with density 0. Its text is stripped of surrounding whitespace, except for a `code` paragraph: that loses only leading and trailing newlines and trailing whitespace, so the indent of its first line is kept.
5. Paragraph `ord` and sentence `ord` count up across the whole document.
6. In one transaction, insert the document (`status="queued"`, `total_sentences` = number of sentence rows, `import_warning` = `doc.warning`, `import_flags` = `doc.flags` joined by spaces; `flags` is left NULL), then sections, paragraphs and sentences with `executemany`.
7. After the transaction, insert up to 200 `doc.concepts` as `terms` with `is_concept=1`.
8. `passages.reindex(db, doc_id)` writes the document's rows in the full-text index `section_fts`.
9. Return `{id, title, warning, sentences, sections}`.

### `load_document` output

```json
{
  "id": "...", "title": "...", "status": "reading", "position": 0, "...": "all documents columns",
  "sections": [
    {"id": "...", "ord": 0, "title": "Abstract", "kind": "abstract", "level": 1,
     "background": 0, "hidden": 0, "prediction": "", "prediction_check": "",
     "paragraphs": [
       {"id": "...", "ord": 0, "kind": "text",
        "sentences": [{"ord": 0, "text": "...", "words": 12, "density": 0.31, "personal": 0, "read": 0}]}
     ]}
  ]
}
```

A paragraph has `asset` only when it is set. Sections with no paragraphs are left out (this is how a section emptied by a split disappears).

---

## 9. The import pipeline

### 9.1 The shape: `importers/model.py`

```python
@dataclass
class PPara:
    text: str
    kind: str = "text"   # text | code | caption | equation | reference | list | fragment
    image: bytes | None = None   # PNG of a PDF display equation

@dataclass
class PSection:
    title: str
    paras: list[PPara]
    level: int = 1
    kind: str | None = None      # None -> detected from the title on save

@dataclass
class ParsedDoc:
    title: str
    sections: list[PSection]
    source_type: str
    warning: str | None = None
    concepts: list[str] = []
    flags: list[str] = []         # what is odd about the file itself, e.g. "hidden_text"
```

`ParsedDoc.non_empty()` drops blank paragraphs, then sections with no paragraphs, and returns the document. `ImportFailed` is the exception whose message is shown to the user. `flags` is filled only by the PDF importer today; `save_parsed` stores it in `documents.import_flags`.

Every importer returns a `ParsedDoc`. Every import path ends in `store.save_parsed`.

### 9.2 Entry points: `importers/__init__.py`

| Name | What it does |
|---|---|
| `TEXT_EXT` | `.md`, `.markdown` -> markdown; `.txt`, `.text`, `.rst` -> text |
| `CODE_EXT` | Imported from `code_import.py`: the code extensions (section 9.5) |
| `keep_original(data: bytes, ext: str) -> str` | SHA-256 of the bytes; writes `library/<hash><ext>` if not already there; returns the hash. The same file imported twice is stored once |
| `_plain_fallback(title, text, reason) -> ParsedDoc` | One section titled "Text". Paragraphs are the text split on blank lines; if there is no text, one paragraph holding the reason. `warning` = the reason |
| `import_bytes(db, filename, data, why="") -> dict` | A file. See below |
| `import_text(db, title, text, fmt="markdown", why="") -> dict` | Pasted text. Title defaults to "Pasted text". No sections -> `ImportFailed("There is no text to import.")`. Keeps the text as `.md` or `.txt`. `source="pasted"` |

**`import_bytes`**

1. Extension from the file name, lower-cased. Title stem = file name without extension, underscores to spaces, or "Untitled".
2. An extension that is not `.pdf`, not in `TEXT_EXT`, not in `CODE_EXT` and not empty: `ImportFailed("Unsupported file type '<ext>'. Use PDF, Markdown, text or a code file.")`. This comes before anything is stored, so no copy of the file is kept.
3. `keep_original` runs for every file that passes step 2.
4. `.pdf`: `parse_pdf(path, fallback_title=stem)`.
   - `ImportFailed` (scanned, password, cannot open, more than `MAX_PAGES` pages): try `plain_text(path)`; use whatever text comes out in `_plain_fallback` with the failure message as the warning. When that text is not empty, the document gets the flag `hidden_text`: the parser found nothing a reader could read, yet the file holds text. A PDF over the page cap takes this path too, so it is flagged although nothing in it is hidden (see "Things in the code that look unintended").
   - Any other exception: log it, and fall back with no text and the message "The PDF parser failed (<ExceptionName>). The original file is kept."
5. A `CODE_EXT` extension: decode as UTF-8 with replacement, then `parse_code(text, <file name with its extension>)`. `ImportFailed` (the file is empty) -> `_plain_fallback` with the text and the message as the warning.
6. Anything else (a `TEXT_EXT` extension or no extension; step 2 let nothing else through): decode as UTF-8 with replacement; Markdown extensions go to `parse_markdown`, the rest to `parse_text`. No sections -> fallback "The file looks empty."
7. `save_parsed(db, doc, source=filename, file_hash=digest, why=why)`.

**The fallback rule in short.** A file that cannot be parsed still becomes a document with `source_type="plain"`, an `import_warning`, and the original kept in `library/`. Only two cases answer 422 instead: an unsupported extension (nothing is kept for it) and empty pasted text.

**Where originals go.** `library/<sha256><ext>` for files and pasted text; a code file keeps its own extension (`<sha256>.py`). Equation pictures go to `library/assets/<document id>/<paragraph id>.png`.

### 9.3 PDF: `importers/pdf_import.py`

PDFium (through `pypdfium2`) gives characters with boxes, sizes and fonts. The module builds lines, then blocks, then sections.

**Public names**

| Name | What it does |
|---|---|
| `PDFIUM_LOCK` | A `threading.RLock`. PDFium is not thread-safe. `parse_pdf` and `plain_text` hold it for their whole run. `lectures.py` takes the same lock when it renders pages |
| `parse_pdf(path: str, fallback_title: str = "Untitled") -> ParsedDoc` | Takes the lock and calls `_parse_pdf` |
| `plain_text(path: str) -> str` | Takes the lock; raw text page by page, joined by blank lines, at most `MAX_PAGES` pages (the whole read holds the lock). The last resort |
| `MAX_PAGES` | 3,000 (milestone 4.5, finding L7). `_parse_pdf` raises `ImportFailed` for a longer PDF: "This PDF has N pages; Readhold reads the structure of up to 3,000. It is shown as the plain text of its first 3,000 pages; the original file is kept." That sentence becomes the document's warning through the fallback. The cap keeps one import from holding `PDFIUM_LOCK` (and with it every lecture page render) for minutes |
| `Block` | A paragraph-sized piece: `page, x0, y0, x1, y1, text, size, bold, lines, tabular, image`. Coordinates are measured from the top of the page |

**Constants**

| Name | Controls |
|---|---|
| `KEYWORD_HEADINGS` | Heading words (abstract, introduction, background, related work, method, approach, experiments, results, evaluation, discussion, conclusion, references, bibliography, acknowledgments, appendix), with an optional number in front |
| `NUMBERED_HEADING` | "3.1 Title" style lines: a number (or roman numeral, or A to H) then a capital, no full stop, up to about 80 characters |
| `CAPTION` | Lines that start with Fig/Figure/Table/Tab/Algorithm/Listing and a number |
| `MATH_CHARS` | Math symbols and Greek letters |
| `EQ_SYMBOLS` | Looser formula characters (`· − ∗ + / ( ) ^ _ |` and the double bar) |
| `BOLD_FONT` | Font names that mean bold |
| `LIGATURES` | Replaces the ff/fi/fl/ffi/ffl ligatures and drops the soft hyphen |
| `SECTION_NUMBER` | A bare section number, so "1" followed by a gap and "Introduction" is not read as table cells |
| `TABLE_SEGS` | `3`. A row with this many pieces (two or more wide gaps) is a table row |
| `PROSE_WORD` | A word of three or more letters; used to tell prose from formulas |
| `EQ_NUMBER`, `EQ_NUMBER_END` | "(3)" alone, and "(3)" at the end of a line |
| `EQ_RENDER_SCALE` | `3` (216 dpi) for equation crops |
| `TOO_SMALL_PT` | `1.0`. A character whose height on the page is above 0 and below this is dropped |
| `FLAG_AT` | `15`. This many dropped characters, or this many pale ones, in the whole file give the document the flag `hidden_text` |
| `UNSEEN` | `{"dropped": 0, "pale": 0}`: module-level counters for the file being parsed. `_parse_pdf` sets both to 0 when it starts; `_lines` counts. Safe only because every parse holds `PDFIUM_LOCK` |

**Step 1: characters to lines (`_lines`).** Walks PDFium's characters in its reading order. A new line starts when the next glyph is not beside the current line (more than 3 em to the right, or too far left) or not on its baseline (middle more than 0.45 em outside the line's box). Smaller glyphs get more leeway to the left, so stacked superscripts and subscripts stay on the line. PDFium's own line break is honoured unless the text carries on at the same height. A gap wider than 1 em inside a line adds to `segs` (table cells). PDFium's soft-hyphen marker (code 2) sets `hyphen`. Bold comes from `_font_is_bold` (font weight >= 600 or a name matching `BOLD_FONT`, cached per font). Lines where at least half the glyphs are rotated are dropped (the arXiv margin stamp).

**Text a reader cannot see (`_lines`, milestone 1.2 of the AI plan).** Two checks run on every character that is not a space, before it joins a line:

- **Dropped.** The height the character has on the page (`seen`: the height of its loose box, `FPDFText_GetLooseCharBox`; the font size when PDFium gives no box) is above 0 and below `TOO_SMALL_PT`, or the character's box lies wholly outside the page (right of it, left of it, above it or below it). The character does not become part of the document. `UNSEEN["dropped"]` goes up by one.
- **Kept and counted.** The fill colour is fully or almost fully transparent (alpha 8 or less of 255) or white or almost white (red, green and blue all 250 or more). The character stays in the text, because white text on a coloured band or a dark picture is ordinary and the importer cannot tell the two apart. `UNSEEN["pale"]` goes up by one.

The font's nominal size (`FPDFText_GetFontSize`) does not include the scaling of the text matrix, so it is not what decides. A 0.5 pt font drawn 24 times larger is 12 pt on the page and is kept; a 12 pt font drawn at 3 percent is dropped. When the nominal size and `seen` differ by more than 2 times either way, `size` becomes `seen`, so line spacing and heading detection also go by the size on the page.

When either count reaches `FLAG_AT`, `_parse_pdf` adds `hidden_text` to `ParsedDoc.flags`. Fewer than 15 dropped characters are dropped without a flag. The flag says only that the file holds such text; it does not say where.

What this does not catch, measured with generated files on 2026-11-25:

- Text drawn with the invisible render mode (mode 3, the text layer of a scanned-and-recognised PDF) is kept and not counted.
- Text behind a picture or a filled shape, text in the same colour as a non-white background, and text in form fields, annotations or metadata are not detected. (The last three are never read by the importer at all, except the metadata title.)
- **The fallback path skips both checks.** When `_parse_pdf` raises `ImportFailed` (under 50 characters left, for instance because everything else was dropped), `import_bytes` falls back to `plain_text`, which returns PDFium's raw text: the dropped characters are back in the document. The document does get the `hidden_text` flag, because the fallback found text (section 9.1). The other side of that rule: an honest PDF with fewer than 50 characters of text is flagged too.

None of this is the safety boundary. Whatever text a document holds, hidden or not, reaches a model only inside a `<source>` fence that says it is data (`ai.guard.pack`, chapter 3, section 7b).

**Step 2: lines to blocks (`_blocks`, `_same_block`, `_make_block`).** Pieces on the same baseline are first joined into one row ("1" + "Introduction", or the cells of a table row). A row joins the block above unless one of these holds:

- the font size changes by more than `max(0.6, 8% of em)`;
- one is a table row and the other is not;
- the vertical gap is more than 0.65 em, or it overlaps upward by more than 0.5 em;
- there is no horizontal overlap (another column);
- a centred formula line starts or ends (indented by 2.5 em on both sides and `_line_mathy`);
- the block is a single all-bold line and the next line is mostly not bold;
- the block's last line ends a sentence and the new line is indented, or that last line was short.

`_make_block` joins words hyphenated across a line break ("represen-" + "tations"), takes the most common font size, calls the block bold when over 60% of its glyphs are bold, and `tabular` when most rows are table rows.

**Step 3: display equations (`_equations`, `_eq_seed`, `_eq_like`, `_crop`).** A PDF holds no LaTeX, so a displayed formula is kept as a picture.

- A block is a seed if it is a bare equation number; or it ends in "(n)", looks like a formula and has at least one math symbol; or it is centred in its column with a math score of 4 or more and at most 10 prose words; or it is short with 2 or more `MATH_CHARS` and at most 3 prose words.
- The group grows to take in neighbouring formula-like blocks (or a number) that overlap vertically within 0.35 em, staying in the seed's column on a two-column page.
- A group with only a number, or taller than 14 em, is skipped.
- `_crop` renders the group's box (3 pt padding, scale 3, transparent background) to PNG. If rendering fails it returns `None` and the blocks stay as they were; a missing picture never fails the import.
- The group is replaced by one block whose text is the formula's characters plus its number and whose `image` is the PNG.

**Step 4: document level (`_parse_pdf`).**

1. Open with `_open`, which turns a password error into `ImportFailed("This PDF is password-protected.")` and any other failure into `ImportFailed("Could not open the PDF: ...")`.
2. Per page: `_equations(page, _blocks(page, pno))`. Read the metadata title.
3. Under 50 characters of text in total -> `ImportFailed` saying it looks like a scanned PDF (OCR is not supported).
4. **Body size** = the font size carrying the most characters.
5. **Running headers and footers.** Blocks in the top or bottom 7% of a page are counted with digits replaced by `#`. `_is_running_header` drops an edge block that repeats, or that is just a page number.
6. **Title.** The largest-font block in the top 40% of page 1 with under 250 characters, if its size is over 1.2 times the body size. Else the metadata title (longer than 3 characters and not ending in `.dvi`, `.doc`, `.tex`). Else the fallback.
7. **Reading order.** `_column_order` sorts each page: blocks that span the middle cut the page into bands; inside a band the left column is read before the right.
8. **Headings.** The first section is "Front matter". A block starts a new section when it is not an equation, its first line has at most 12 words and under 100 characters, it has at most 2 lines or a first line under 40 characters, the same first line has not been a heading before, and one of:
   - size at least 1.12 times body and at most 3 lines;
   - `KEYWORD_HEADINGS` matches and the block is bold, or over 1.05 times body, or the line is under 30 characters;
   - `NUMBERED_HEADING` matches and the block is bold or over 1.02 times body.

   "Abstract—We propose..." on one line becomes an "Abstract" section with the rest as its first paragraph. Text on the lines after a heading becomes that section's first paragraph.
9. **References and after.** A heading whose kind is `references` turns on `in_refs`: every paragraph until the next heading is a `reference`. A later heading of kind `other` gets `kind="appendix"` (material after the references is supplementary).
10. **Paragraph kind (`_para`)**, first match wins:

| Test | Kind |
|---|---|
| Inside references | `reference` |
| Block has a picture | `equation` (with image) |
| Matches `CAPTION` | `caption` |
| Under 200 characters, 2+ math symbols, over 3% symbols, fewer than 8 prose words | `equation` (text only) |
| `tabular` block | `fragment` |
| Below 70% of the page height and smaller than 0.95 times body | `caption` (footnote) |
| Smaller than 0.85 times body and under 800 characters | `caption` (small print) |
| 5 words or fewer and no closing punctuation | `fragment` |
| Otherwise | `text` |

11. **After the walk.** `_numbered_levels` sets `level` from the section number ("6.1" is level 2, at most 3) and lets a subsection of kind `other` inherit its parent's kind. `_split_references` joins the reference text and splits it at `[n]` markers. `non_empty()` drops empty sections. With one section or none left, `warning` is set to "No headings were detected; ... Use Fix structure to split it." `_merge_broken_paragraphs` joins a text paragraph to the previous text paragraph when that one does not end a sentence and this one starts lower-case, with only captions or fragments between them (never across an equation).

### 9.4 Markdown and text: `importers/markdown_import.py`

| Name | What it does |
|---|---|
| `_md` | A mistune parser that returns a token tree (`renderer=None`) with the `table`, `strikethrough` and `math` plug-ins |
| `parse_markdown(source: str, fallback_title: str = "Untitled") -> ParsedDoc` | Markdown to sections |
| `parse_text(source: str, fallback_title: str = "Untitled") -> ParsedDoc` | Plain text to sections |
| `_inline_text(children, concepts) -> str` | Flattens inline tokens to plain text |
| `_looks_like_money(raw) -> bool` | Tells "$5 and $10" from a formula: starts with a number then a space, no backslash, none of `= ^ _ { }` |

**`parse_markdown` rules**

| Token | Result |
|---|---|
| First `#` heading, before any paragraph | The document title (not a section) |
| Any other heading | A new section with that `level` |
| Paragraph | A `text` paragraph |
| Fenced or indented code | A `code` paragraph |
| `$$...$$` block | An `equation` paragraph `\[tex\]`; a `\tag{n}` is moved out as " (n)" |
| List item | A `list` paragraph each. A full stop is added if the item has no closing punctuation, so the sentence splitter keeps items apart. Nested lists are walked |
| Block quote | Its content is walked as normal blocks |
| Table | One `code` paragraph, rows joined by newlines, cells by ` | ` |
| Raw HTML block | Dropped |

Inline: code spans keep their text, and those 2 to 39 characters long are collected as concepts; `$...$` becomes `\(...\)` unless it looks like money; an image becomes `[image: alt]`; links keep their text only.

The first section starts as "Start". It is removed if empty; otherwise it is renamed "Opening" when there are other sections or a title. `concepts` is the sorted, de-duplicated list. `source_type="markdown"`.

**`parse_text` rules.** Split on blank lines. A one-line block that `looks_like_heading` is the title if it is the very first block, else a new section. A multi-line block whose first line looks like a heading and is under 60 characters starts a section with the rest as its paragraph. Everything else is a `text` paragraph. The first section is "Opening". `source_type="text"`.

### 9.5 Code files: `importers/code_import.py`

A code file becomes a document with one section per top-level definition. The module reads the text line by line and only looks at how lines start. Nothing is run and nothing is parsed as a language.

| Name | What it does |
|---|---|
| `CODE_EXT` | Extension -> language: the key into `RULES` |
| `NAME` | The pattern of an identifier: a letter, `_` or `$`, then word characters or `$` |
| `RULES` | Per language, an ordered list of `(pattern, title)`. A pattern is tried with `match` on a line that starts at the left margin; its groups fill the title |
| `LEAD` | A line that belongs to what follows: it starts (after optional spaces) with `#`, `//`, `/*`, `*`, `@`, `--`, or `[` and a letter (an attribute) |
| `PY_METHOD` | `def` or `async def` and a name, for Python methods |
| `MAX_HEADING_LINE` | 1,000 characters (milestone 4.5, finding L6). A longer line is never a heading and is not run through the patterns, so a crafted line (`impl ` followed by 100,000 `a<`) cannot make a pattern run for long (`tests/test_security.py` imports one in under 5 seconds) |
| `_title(rules, line) -> str \| None` | `None` for a line over `MAX_HEADING_LINE`; else the title from the first rule that matches, else `None` |
| `_paras(lines) -> list[PPara]` | Blank lines separate paragraphs. Each paragraph is its lines joined by newlines, untouched, with kind `code` |
| `parse_code(text: str, filename: str) -> ParsedDoc` | See below |

**`CODE_EXT`**

| Language | Extensions |
|---|---|
| `python` | `.py`, `.pyi` |
| `js` | `.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.tsx` |
| `go` | `.go` |
| `rust` | `.rs` |
| `c` | `.java`, `.c`, `.h`, `.cpp`, `.cc`, `.hpp`, `.cs`, `.kt`, `.swift`, `.php` |
| `ruby` | `.rb` |
| `shell` | `.sh`, `.ps1` |
| `plain` | `.sql`, `.css`, `.json`, `.toml`, `.yaml`, `.yml` |

**`RULES`: what starts a section, and its title**

| Language | A line at the margin that starts with | Title |
|---|---|---|
| `python` | `def` or `async def`; `class` | `def <name>`; `class <name>` |
| `js` | `function` (after optional `export`, `default`, `async`; also `function*`) | `function <name>` |
| | `class` (after optional `export`, `default`, `abstract`) | `class <name>` |
| | `interface`; `type <name>` followed by `=` or `<`; `enum` or `const enum` (each after optional `export`, `declare`) | `interface <name>`; `type <name>`; `enum <name>` |
| | `const`, `let` or `var` (after optional `export`) set to a `function`, an arrow function with brackets, or a one-name arrow function | `const <name>` (also for `let` and `var`) |
| `go` | `func`, with an optional receiver in brackets; `type` | `func <name>`; `type <name>` |
| `rust` | `fn` (after optional `pub`, `pub(...)`, `async`, `unsafe`) | `fn <name>` |
| | `struct`, `enum`, `trait`, `mod`, `union` (after optional `pub`) | `<keyword> <name>` |
| | `impl` | `impl <last name on the line>` |
| `c` | `class`, `interface`, `struct`, `enum`, `namespace`, `record`, `object`, `protocol`, `extension`, `trait` (after modifiers such as `public`, `static`, `final`, `data`) | `<keyword> <name>` |
| | `fun`, `func` or `function` (after modifiers such as `public`, `override`, `suspend`) | `function <name>` |
| | A C-like function: a type, a name, an opening bracket, and no `;` on the rest of the line. A line that starts with `if`, `for`, `while`, `switch`, `return`, `else`, `do`, `catch`, `using` or `typedef` is not one | `function <name>` |
| `ruby` | `def`; `class` or `module` | `def <name>`; `class <name>` or `module <name>` |
| `shell` | `name()` with an optional `function` before it; `function name` | `function <name>` |
| `plain` | Nothing | |

**`parse_code` step by step**

1. The language is `CODE_EXT[extension]`, or `plain` for an unknown one. Line ends are normalised to `\n` and the text is split into lines. If every line is blank: `ImportFailed("The file is empty.")`.
2. Walk the lines, skipping blank ones. A line at the margin (its first character is not whitespace) that matches a rule starts a level-1 section.
3. Python methods. A `class` section sets the owner to the class name. Any other definition clears it, and so does an ordinary line at the margin: one that is not a `LEAD` line and does not start with `)`, `]` or `}`. While there is an owner, an indented `def` or `async def` starts a level-2 section titled `<Class>.<method>` when its indent is the same as the first line of the class body (4 spaces, 2 spaces or a tab). A `def` nested deeper is not a section.
4. Leading lines. Each section start moves up over the lines right above it that are not blank and match `LEAD`: comments, decorators, attributes. For a level-1 section those lines must be at the margin too. The move stops at the line after the previous section's first line.
5. Sections. No section starts: one section titled with the file name, holding every line. Otherwise the lines before the first start become "Top of file" (when there are any), and each section runs to the next start; the last runs to the end of the file. So code that follows a definition at the margin stays in that definition's section. Titles are cut to 200 characters. Every section has kind `other`, so no section of a code file is marked background or hidden.
6. `non_empty()` drops empty sections; if none is left, `ImportFailed("The file is empty.")`. The document title is the file name, and `source_type="code"`.

No line is lost and none is repeated: joined in order, the paragraphs give back every non-blank line of the file (`test_python_sections_are_definitions`).

**What happens to a `code` paragraph afterwards.** `save_parsed` stores it whole as one sentence with density 0 and keeps the indent of its first line (section 8). It is not in `PACED_KINDS`, so the pacer does not visit it and `key_sentence_stats` does not count it: a document that is all code has a `progress` of 0 out of 0. The reader draws it as `<pre class="p code">` with no sentence elements inside (chapter 5).

---

## 10. Text rules

### 10.1 `text.py`

| Name | What it does |
|---|---|
| `ABBREVIATIONS` | Lower-case tokens after which a full stop does not end a sentence (`e.g`, `i.e`, `et al`, `fig`, `eq`, `vs`, titles, month names, ...) |
| `MATH_SPAN` | Matches `\( ... \)` and `\[ ... \]` |
| `SECTION_RULES` | Ordered `(pattern, kind)` list |
| `BACKGROUND_KINDS` | `{"related", "appendix"}` |
| `HIDDEN_KINDS` | `{"references"}` |
| `normalize_ws(text) -> str` | Drops soft hyphens, turns no-break spaces into spaces, joins words hyphenated across a line break, collapses whitespace, and removes the space between a formula and following punctuation or a preceding bracket |
| `count_words(text) -> int` | Words outside formulas, plus about one word per 6 characters of LaTeX (at least 1 per formula) |
| `split_sentences(text) -> list[str]` | See below |
| `math_to_markdown(text) -> str` | `\(x\)` -> `$x$`, `\[x\]` -> `$$x$$` |
| `plain_math(text) -> str` | Removes the delimiters, keeps the LaTeX |
| `section_kind(title) -> str` | See below |
| `looks_like_heading(line) -> bool` | For plain text |

**Sentence splitting.**

1. `normalize_ws`.
2. `_hold_math` swaps each formula for a numbered placeholder wrapped in two private-use characters (U+E000 and U+E001), so the rules never look inside LaTeX.
3. `_split` looks for a boundary: one of `. ! ? …`, optional closing quotes or brackets, whitespace, then an optional opening quote or bracket and a capital letter or digit.
4. A boundary is skipped when the word before the full stop is in `ABBREVIATIONS` or is a single letter (an initial).
5. A piece under 4 characters, or made only of digits, dots and brackets, is joined to the piece before it (list markers such as "1.").
6. `_restore_math` puts the formulas back.

**Section kinds.** `section_kind` strips a leading number ("3.1 ", "IV. ", "A. "), lower-cases, and returns the kind of the first matching rule in `SECTION_RULES`, else `other`. Order matters: for example "related work" is tested before "method", and `acknowledg...` maps to `references` so it is hidden. Only `abstract`, `intro`, `references`, `acknowledg` and `appendix` are anchored to the start of the title; the others match anywhere in it.

**`looks_like_heading`.** False for an empty line, a line over 90 characters, a line ending in `. , ; :` (unless it is just a number like "2.1."), or more than 10 words. True for a numbered line followed by a capital; a line of 4 words or fewer whose `section_kind` is not `other`; an all-capitals line of 8 words or fewer; or 6 words or fewer where all but at most one start with a capital and the line does not end in `?`.

### 10.2 `density.py`

`score(sentence) -> float` returns 0 (easy) to 1 (very dense), rounded to 3 places. An empty sentence scores 0.

`features(sentence) -> dict`:

| Feature | Formula |
|---|---|
| `words` | Number of words (not weighted) |
| `rare_ratio` | Share of words longer than 3 letters whose Zipf frequency (`wordfreq`, English) is below `RARE_ZIPF = 3.2` |
| `length` | `min(words / 40, 1)` |
| `numbers` | `min(count of numbers / 4, 1)` |
| `symbols` | `min(count of math symbols and Greek letters / 4, 1)` |
| `acronyms` | `min(count of all-capital tokens / 3, 1)` |
| `long_words` | `min(3 * words of 10+ letters / words, 1)` |

```
WEIGHTS = rare_ratio 0.42, length 0.18, numbers 0.12, symbols 0.12, acronyms 0.08, long_words 0.08
score   = clamp(1.6 * sum(weight * feature), 0, 1)
```

`_zipf` caches up to 50,000 lookups. `wordfreq` reads frequency lists bundled with the package; there is no network use.

### 10.3 `terms.py`

**`find_acronyms(sentences: list[str]) -> dict[str, str]`.** Looks for `(ABC)` or `(ABCs)`: a capital followed by 1 to 9 letters or digits. The acronym's capitals and digits are its letters (at least 2). It takes the words before the bracket (up to letters + 4 of them) and `_match_initials` finds the shortest run, ending at the bracket, whose initials spell the acronym. Words in `STOP` (of, and, the, for, ...) are skipped when taking initials and cannot start the run; hyphenated words give one initial per part. The first expansion found for an acronym wins.

**`find_definitions(term, sentences: list[tuple[int, str]], limit=5) -> list[dict]`.** Tries each pattern in `DEF_PATTERNS` (case-insensitive) on every sentence. A sentence is recorded once, by the first (strongest) pattern that hits.

| Label | Shape | Score |
|---|---|---|
| `defined as` | "X is defined as / is called" | 1.0 |
| `we define` | "we define / call / term / denote / refer to ... X" | 0.95 |
| `refers to` | "X refers to / denotes / means / stands for / represents" | 0.9 |
| `known as` | "called / known as / termed / dubbed / named X" | 0.85 |
| `X is a` | "X is a / an / the" | 0.8 |
| `X:` | "X: " | 0.6 |
| `X (…)` | "X (" | 0.4 |

Hits are sorted by score, then by sentence order. If nothing matches, the first sentence that mentions the term is returned with pattern `first use` and score 0.1. Each hit is `{sentence, text, pattern, score}`.

---

## 11. Invariants and gotchas

**Storage**

- `sentences.ord` is fixed for the life of a document. Highlights, notes, `documents.position`, `questions.source_sentence` and the export's `s<ord>` markers all point at it. The Fix-structure routes move paragraphs between sections but never renumber sentences or paragraphs.
- Never hard-delete. Use `db.soft_delete`, and filter `deleted=0` in every read.
- A schema change is a new file in `readhold/migrations/`. `_split_sql` only removes lines that start with `--` and then splits on every `;`. A semicolon inside a trailing comment or a string literal would cut a statement in two. Triggers are not supported for the same reason.
- `DB.transaction()` does not nest.
- A raw `UPDATE` that sets `updated_at` must also set `device_id` (to `db.device`), as `db.update` does. In `server.py` this holds for `api_position`, `api_read`, `api_section_merge` and the paragraph move in `api_split`.
- `save_parsed` writes equation pictures before the transaction and concept terms after it. Neither is rolled back if the transaction fails.
- `section_fts` must be rebuilt after every change to a document's structure. Call `passages.reindex(db, doc_id)` after anything that adds or removes a document, renames a section, or moves paragraphs between sections. The five call sites today: `store.save_parsed` (import), and in `server.py` `api_section_patch` (only when `title` is sent), `api_section_merge`, `api_split` and `api_doc_delete`. A new structure route needs the same call. `api_doc_delete` also calls `ai.results.forget_document`; a new way to remove a document needs that call too. `passages.ensure_index` at start only adds documents that have no rows at all; it does not repair rows that are out of date.
- `section_fts` is derived data and is not in `EXPORT_TABLES`. Keep it out: it can always be rebuilt from `sections` and `sentences`.
- Time strings come in three precisions: `db.now()` (milliseconds), `services._iso` (seconds), and `datetime.isoformat()` (microseconds) in a few `since` values. All are UTC with `+00:00` and are compared as text. Local time is used only for "today": daily backups, `reviews_today`, `daily_stats`, the count routes.

**Safety**

- The guard is the only authentication. A new route gets it for free; a route must never be added outside `create_app` or its `register` functions. A write is refused unless it comes from the app's own page (`Origin`, `Sec-Fetch-Site`); a new front-end call that writes goes through `api.ts`, which sends from the same origin.
- A refused request does not echo its input: keep the `invalid_request` handler. A route's own `HTTPException` detail is a sentence written in the code; the settings route names the key, never the value. (One route still quotes what was sent: Organize's bad-tag message shows up to 50 characters of the tag, chapter 3, section 7c.)
- A key-shaped value is never stored in a setting, of any key. A new setting needs nothing for that; a new route that stores free text the user typed is not covered and must check it itself if it can hold a key.
- `socket` and `webbrowser` are imported only by `__main__.py`, `ssl` and `subprocess` by no module of `readhold/` (`tests/test_no_network.py`, `LOW_LEVEL`). The server's socket is bound once in `__main__.bind`; do not let uvicorn bind a port itself.
- Imported text is stored as plain text. The Markdown importer drops HTML blocks. The front end must keep rendering with `textContent`.
- The asset route serves only names that match the pattern and are in the database. Keep both checks.
- Every PDFium call must hold `PDFIUM_LOCK`. Use `parse_pdf` and `plain_text`, not the underscore versions. The `UNSEEN` counters in `pdf_import.py` are module-level and rely on the same lock.
- A flag never blocks. `hidden_text` and `instructions` are marks for the reader; the document is imported, read and searched as usual. `_import_result` calls `flag_document` inside a `try`: if it raises, the failure is logged, the answer carries `flags: []`, and `documents.flags` stays NULL so the next start looks again.
- `documents.flags` is NULL until `flag_document` has looked at the document. `import_bytes` and `import_text` called directly (as tests do) leave it NULL; the import routes and the next start fill it. Keep NULL and the empty string apart.
- The app connects to nothing by itself, and the server only answers on `127.0.0.1`. The one connection it can make is to the AI model the user chose, and only while `ai_mode` is not `off`. A network client is imported in `readhold/ai/adapters.py` and nowhere else in `readhold/`, the front end only talks to its own server, and `/api/import/url` does not exist. `tests/test_no_network.py` enforces all three. Keep it that way: a new importer reads a file the user picked or text the user pasted, and never downloads; a new AI feature calls the port and never opens a connection itself.
- Every guard answer carries the CSP, `nosniff`, `no-referrer` and a `Cache-Control` header, the 401 and 403 refusals included. The guard only fills in `Cache-Control: no-store` when the route set none. Every answer that reached a route also carries COOP, CORP and `Permissions-Policy`.
- An import is bounded: 50 MB, at most `MAX_PAGES` (3,000) PDF pages read for structure and for the plain-text fallback, code lines over `MAX_HEADING_LINE` (1,000 characters) never matched against the heading patterns. A new importer needs bounds of its own.
- A request model with a required text extends `bodies.Body`, so a text of only spaces answers 422. `Body` does not trim.

**Behaviour to keep in mind**

- A failed parse must still end in a saved document. If you add a file type, give it the same fallback.
- `import_bytes` checks the extension before it calls `keep_original`, so a rejected file type leaves no copy in `library/`. A new file type must be added to that first check as well as to its own branch.
- Cards are tied to their source by `(source_type, source_id)`. `upsert_card` on a soft-deleted card brings it back with its old schedule, unless it is `suspended`: a card the reader deleted stays deleted until its Undo.
- A new kind of record the reader can delete goes into `trash.KINDS` (the table comes from there, never from the request), with its linked rows in `delete` and `restore` and what its restore needs in `_check_restore`. A read that shows such records filters `deleted=0`, and so must every join through them (the day story and the weekly review join goals and habits for that reason).
- A focus run's `spent_ms` on its task is taken off on delete and added on restore only when the row really changes state, so a second delete or Undo never counts twice.
- A card does not outlive its reason: clearing a question's answer removes its card (`api_q_patch`), and changing a highlight's `type` removes the card of the old type (`sync_highlight_card`).
- `EXPORT_TABLES` is a hand-kept list. A new table that holds the user's work must be added to it, or the full export leaves it out.
- A new setting must be added to `DEFAULT_SETTINGS` or `PUT /api/settings` will drop it silently.
- `PACED_KINDS` in `store.py`, the kind lists in the SQL of `doc_sentences` and `key_sentence_stats`, and the kinds the importers emit must stay in step. A new paragraph kind is unpaced and uncounted until it is added in those places.
- Changing `section_kind` or `SECTION_RULES` changes which sections new imports mark as background or hidden. Existing documents keep what was stored.
- Changing `density.score` affects only new imports; scores are stored per sentence.

### Things in the code that look unintended

These were seen while reading. None is confirmed as a bug by a failing test.

- **Weekly review and deleted documents.** `weekly_review` does not filter `d.deleted=0` in `explained` and `open_confusions`; `home` does for its confusions.
- **A long PDF is flagged.** A PDF over `MAX_PAGES` falls back to plain text through the same branch as an unreadable one, so it gets `hidden_text` (the ⚠ mark) although nothing in it is hidden.
- **The key check of the settings route** looks at top-level string values only; a key inside an object value (`comfort_by_type`) would be stored.
- **Unchecked ids.** `/position`, `/read`, `/slow`, `PATCH /api/notes/{id}` (which reads the old text first and empties `origin` only when the text changed), `DELETE` on notes, ideas, questions, terms and highlights, `PATCH /api/sessions/{id}` and `/api/questions/{id}/link` do not check that the row exists (or is not deleted). `POST /api/notes` does not call `need_doc`; an unknown `document_id` fails the foreign key and comes back as a 500.
- **Split is not atomic.** `api_split` renumbers sections in a transaction, then inserts the section and moves paragraphs outside it.
- **The plain-text fallback brings dropped text back.** The document is flagged `hidden_text`, but the text is in it. See "The fallback path skips both checks" in section 9.3.
- **A branch that seems unreachable.** In `_parse_pdf`, `elif b.lines > 3 and b.size < body * 1.12 and not rest` needs a block of more than 3 lines with no text after the first line. `rest` is non-empty whenever the block has a second line.

---

## 12. Tests

`tests/conftest.py` gives four fixtures:

| Fixture | What it gives |
|---|---|
| `home` | Sets `READHOLD_HOME` to pytest's temporary folder |
| `db` | `open_db()` in that folder: a fresh database with all migrations |
| `client` | `create_app(db, "test-token", {"testserver"})` in a `TestClient`, already signed in through `/auth` |
| `sample_md` | `SAMPLE_MD`: a short paper with Abstract, Introduction, Related Work, Method (with a code block and a backtick term), Results and References |

What each file checks for this chapter's code:

| Test file | Covers |
|---|---|
| `test_api.py` | The guard (no token 401, wrong token 401, header token 200, wrong host 403, bad `/auth` token 401, CSP present). Import of pasted Markdown, section kinds and flags, sentence `ord` running 0..n, density in range. Position, read marks and the resume card. Split, rename, merge-up. Templates and learning. All four card types, the cloze front, due count, a review moving `due` later. Summary (claim with its evidence, acronyms, confusions), the idea row, Markdown export. `/define`. Sessions, stats, streak, `next_step`. Settings ignore unknown keys. Full export, manual backup. The pre-migration backup on upgrade. `test_fixes_from_the_code_guidebook`: a 401 carries the CSP and `nosniff`; a normal answer has `Cache-Control: no-store`; clearing an answer removes the question card; changing a highlight's type removes its `definition` or `cloze` card; an unsupported file type is refused and `library/` is unchanged; `EXPORT_TABLES` holds `todo_items`, `suggestions` and `daily_picks` |
| `test_parsers.py` | Markdown structure, concepts, dropped HTML. Plain-text headings. PDFs made with reportlab: two columns read in order, sections, running footer removed, references split, captions; tables as `fragment`, hyphen joined across a line, footnote as `caption`. A broken PDF falls back to `plain` with a warning and the original kept. A password PDF raises `ImportFailed`. Any files in `tests/fixtures/real/` (git-ignored; the folder may not exist) must import with more than 10 sentences |
| `test_code_import.py` | `parse_code` on a Python file: the sections and their levels (`Top of file`, `def`, `class`, methods at level 2), every paragraph of kind `code`, the comment and decorator kept with their definition, the indent kept, no line lost or repeated. A TypeScript and a Go file: the section titles, the comment above a definition. A file with no definitions is one section named after the file; a blank file raises `ImportFailed`. A 5,000-character line and a tab survive. `import_bytes` on a `.py` file: `source_type` `code`, the stored sentence keeps its indent, the original is kept in `library/` as `.py`, and `.exe` is refused as unsupported |
| `test_passages.py` | The index and its callers in this chapter: a section rename, a merge-up and a document delete are followed by the index; `POST` and `PATCH /api/sessions` set `start_ord` and `last_ord`. The rest is in chapter 3 |
| `test_text.py` | Sentence splitting (abbreviations, decimals, quotes, de-hyphenation, empty input). `section_kind`. `looks_like_heading`. Density ordering (easy below 0.2, dense above 0.5). Acronyms. Definition finder: ranking, first-use fallback, terms with symbols |
| `test_math.py` | No split inside a formula. Formula word count. `math_to_markdown`. Markdown math (inline, block, money). A PDF display equation is cropped to PNG with its number. The picture is stored and served, and the asset route refuses unknown names, other documents and path tricks. `normalize_ws` around formulas |
| `test_reflect.py` | A guess without a definition becomes a card, and the definition later replaces it. Predictions and critique in the Markdown export. Full export leaves out deleted rows. Restore. `touch=false` keeps `queued`. Concept search treats `%` and `_` as text. Session time-box change is saved. Settings rows have sync columns. `energy_feel`. Weekly review contents. The rest of the file tests `compass` and `growth` routes |
| `test_open_findings.py` | For this chapter: `bodies.Body`, through other modules' routes (a required text of only spaces answers 422; a field left out of a patch passes). The rest of the file tests other modules (teach-back, Think, the timer's raw update) |
| `test_delete_everything.py` | Milestone 5.1 (39 tests): every kind of `trash.KINDS` deletes and restores, once per kind; bad ids, unknown kinds and another kind's id are 404 and change nothing; the old habit and goal delete routes undo through the new restore; a deleted card is skipped by `due_cards`, cannot be rated (`review_card`), stays deleted when its term is patched (`upsert_card`) and is back with the new text after Undo; a card that went with its term is not restored; an `ai` card you deleted is not added again; a journal page and its ink go and come back, the day can be written again (one row per day) and a late Undo leaves the new page; a deleted habit leaves the day story; a deleted letter cannot be opened; a focus run takes its session, Stamina's `focused_ms` and its task's `spent_ms`, and two Undos count once; a running timer is 409; `GET /api/timer/recent`; an AI result goes and comes back, not after its document is removed or after `clear_all`; a map link that would loop is 409; a restored goal is parked; a removed check-in brings back the earlier one; a deleted side goal is not counted as parked; `export_all` leaves deleted rows out |
| `test_ai_resume.py` | For this chapter: `ai_results` is in `EXPORT_TABLES`; deleting a document leaves no live `ai_results` row. The test's helper drives `POST /api/documents/{id}/position`, `POST …/read`, `POST /api/highlights` and `POST` / `PATCH /api/sessions` to make a finished reading session. The rest is in chapter 3 |
| `test_ai_explain.py` | For this chapter: a note saved from an explanation is in `GET …/annotations` with `origin` `ai`; `PATCH /api/notes/{id}` with a new text empties `origin`, and with the same text keeps it; a note made with `POST /api/notes` has none; after `DELETE /api/notes/{id}` the kept explanation has `saved` false again. The rest is in chapter 3 |
| `test_ai_guard.py` | For this chapter: a PDF made with reportlab that holds white text, 0.4 pt text and text below the page imports without the last two and gets the `hidden_text` flag; `flag_document` and `flag_new_documents`; `GET /api/documents` returns `flags` as a list; the CSP has no outside address. A 0.5 pt font drawn 24 times larger is imported and a 12 pt font drawn at 3 percent is not, and that document has `hidden_text`; a PDF whose only text is 0.4 pt falls back to plain text and has `hidden_text`. The rest is in chapter 3 |
| `test_no_network.py` | The app connects to nothing by itself. No module in `readhold/` outside `readhold/ai/` imports a network client (`httpx`, `requests`, `aiohttp`, `urllib3`, `httplib2`, `http.client`, `urllib.request`, `ftplib`, `smtplib`, `websockets`, `trafilatura`). Inside `readhold/ai/`, exactly one file does (`adapters.py`), and only `httpx`. No module outside the package imports `ai.adapters`. No file in `web/src/` has a `fetch` to an `http` address, a `WebSocket`, an `EventSource` or `sendBeacon`. `POST /api/import/url` answers 404 or 405. `test_the_calm_tools_are_gone`: `/api/calm` and `/api/calm/notes` answer 404; the settings have no `unstick_button`, `guess_ask` or `steady_pattern`; a timer start that still sends `guess` is accepted and the run has no `guess_hard`. Since 4.5, `LOW_LEVEL`: `socket` and `webbrowser` are imported only by `readhold/__main__.py`, and `ssl` and `subprocess` by no module of `readhold/` |
| `test_security.py` | Milestone 4.5, for this chapter: a write with `Origin: http://127.0.0.1:8888`, `Origin: null`, or `Sec-Fetch-Site` `same-site` or `cross-site` is 403; one with the app's own origin and `same-origin`, or with neither header, is 200; a `GET` with another origin is 200. A Rust file with one 200,005-character line imports in under 5 seconds. With `MAX_PAGES` set to 3, a five-page PDF imports with a warning that names its 5 pages, and holds "Page 2 of" but not "Page 3 of". A key in `tts_voice` answers 422, is not in the answer and is not stored. A question over the length limit answers 422 without the question (or the key in it) in the answer. Two documents titled `CON` export to two different Markdown files, neither `CON.md`. `GET /` has COOP and CORP `same-origin` and a `Permissions-Policy` with `camera=()`. The rest of the file (a model server on another computer) is in chapter 3 |

Not covered by tests, as far as these files show: `winicon`, `__main__` (`bind` included), the daily backup pruning, the `/slow` learning rule, the `flags` field in the answer of the two import routes, a failing `flag_document` inside `_import_result`, a PDF with fewer than `FLAG_AT` hidden characters, and the pale count on its own (the test file trips the flag through its dropped characters as well).
