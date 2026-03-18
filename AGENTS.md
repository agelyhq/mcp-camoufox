# AGENTS.md — Camoufox MCP Server

MCP server exposing Camoufox anti-detect browser control to AI agents. Built with [FastMCP](https://gofastmcp.com/). Uses Playwright (via `camoufox` package) for browser lifecycle; custom JS injection for DOM snapshots and UID-based element targeting.

Package: `camoufox_mcp` — dependencies: `fastmcp>=2.14`, `camoufox[geoip]>=0.4`, `boto3>=1.34`

## Build & Lint

```bash
uv sync --extra dev                    # Install with dev deps
uv run ruff check src/ tests/          # Lint
uv run ruff format src/ tests/          # Format
CAMOUFOX_HEADLESS=true uv run pytest   # Run E2E tests
```

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/). Camoufox binary is auto-fetched on first `main()` call.

## Boundaries

### Always
- Run `ruff check src/ && ruff format --check src/` before declaring work complete
- Every tool returns `str` (or `list` for screenshot) — never raise to the MCP client
- Keep every file under 300 lines
- One tool per file in `tools/`
- Use `from __future__ import annotations` in every module

### Ask first
- Adding new dependencies to `pyproject.toml`
- Modifying `_context.py` helpers (shared across all tools)
- Changing the UID format (`e0`, `e1`, …) or `data-mcp-uid` attribute name

### Never
- Expose browser process details or file paths in tool responses
- Use synchronous I/O in tool handlers (everything is async)
- Modify JS files in `js/` without verifying UID contract

## Architecture

```
MCP Client → stdio → FastMCP (server.py)
                          ↓ lifespan (no browser started)
                     BrowserManager (idle)
                          ↓ start_session(SessionParams)
                     AsyncNewBrowser (camoufox → Playwright)
                          ↓
                     Playwright Browser / BrowserContext
                          ↓ new_page()
                     PageHandle (wraps Playwright Page)
                          ↓ NetworkMonitor + ConsoleMonitor (per page)
                     Captures request/response + console events
```

Single browser process per MCP session. Lazy start: lifespan creates `BrowserManager` but does **not** launch Camoufox. The first `navigate` call triggers `AsyncNewBrowser`; `kill_session` tears it down. Only one active session allowed at a time.

Multi-tab via `BrowserManager.pages` dict (int → PageInfo). Active tab tracked by `active_page_idx`.

## Session Lifecycle

- **Startup** — `_check_s3()` runs in `lifespan` before yielding: verifies S3 is configured and the bucket is reachable via `head_bucket`. Raises `RuntimeError` immediately if not, preventing the server from starting with broken config.
- **`navigate`** — `profile` is **required**. Auto-starts a session if none is running. `SessionParams` (OS, viewport, block flags) used only on first start. GeoIP and humanize always enabled. Proxy from `ServerConfig`.
- **`kill_session`** — Closes browser, zips + uploads profile to S3, deletes temp dir, resets state. Safe when no session is running.
- Profile is pulled from S3 into a `TemporaryDirectory` at session start; pushed back on stop. S3 **must** be configured — missing any `CAMOUFOX_S3_*` var causes startup to fail.
- **Headless** is env-only (`CAMOUFOX_HEADLESS`). Not a session param.

## Project Structure

- `server.py` — Composition root: FastMCP instance, async lifespan (creates BrowserManager, no browser start), `_ensure_browser_binary()` auto-fetch, entry point
- `browser/addons.py` — Addon lifecycle: download `.xpi` (cached in `~/.cache/camoufox-mcp/addons/`), extract to temp dir per session, cleanup on stop
- `browser/config.py` — `S3Config` (OVH S3 credentials) + `ServerConfig` (env-only: headless, proxy, binary, addon_urls, s3) + `SessionParams` (per-session: **profile** required, OS, viewport, block flags)
- `browser/manager.py` — `BrowserManager` (lazy Playwright lifecycle, `start_session`/`stop_session` with single-instance guard, profile pull/push orchestration) + `PageInfo`
- `browser/profile_store.py` — S3 profile sync: `pull_profile()` downloads+extracts zip into tmpdir; `push_profile()` zips+uploads from tmpdir
- `browser/console.py` — `ConsoleMonitor` + `ConsoleEntry`: bounded deque, level filtering
- `browser/network.py` — `NetworkMonitor` + `NetworkEntry`: request/response capture, lazy body fetching
- `browser/page_handle.py` — `PageHandle` wraps Playwright `Page` (navigate, evaluate, screenshot, input, monitors, dialogs)
- `dom/snapshot.py` — JS file loading with dict-based cache
- `dom/uid.py` — `valid_uid()`, `uid_selector()`, `run_js_action()`, `resolve_uid()`
- `dom/actions.py` — `clear_field()`, `scroll_into_view()`, `file_input_selector()`
- `js/` — JS files packaged inside `camoufox_mcp/`
- `tools/_context.py` — `get_manager(ctx)` and `get_page(ctx)` helpers (shared by all tools)
- `tools/navigate.py` — Navigate + lazy session start; `profile` is mandatory
- `tools/kill_session.py` — Kill browser, trigger profile push to S3, reset state
- `tools/<name>.py` — One file per browser tool, each exports `register(mcp)` function

## Conventions

### Layers
- **`browser/`** — Domain. Browser lifecycle via Playwright/camoufox, page abstraction
- **`dom/`** — Domain. JS injection, UID system, DOM actions. Uses `PageHandle.evaluate()`
- **`tools/`** — Application. Thin wrappers that connect MCP context to domain logic. Each file registers exactly one `@mcp.tool()`
- **`server.py`** — Composition root. Wires lifespan + tools. No business logic

### Tool Pattern
Every tool file follows the same structure:
1. Imports from `_context` and domain modules (`dom`, `browser`)
2. `register(mcp: FastMCP)` function containing one `@mcp.tool()` decorated async function
3. Try/except returning human-readable error strings — never raises

### Import Rules
- `from __future__ import annotations` always first
- Runtime imports: only what's needed for execution
- `FastMCP`, `Context` kept as runtime imports with `# noqa: TC002` (FastMCP introspects signatures)
- Type-only imports in `TYPE_CHECKING` blocks

## Invariants

- UIDs match `^e\d+$` — validated inside `run_js_action()` (single enforcement point for all JS actions)
- JS files loaded once and cached in `_JS_CACHE` dict — never re-read from disk
- `BrowserManager.is_running` is `False` until `start_session()` is called (triggered by first `navigate`)
- `BrowserManager.start_session()` raises `RuntimeError` if a session is already running
- `BrowserManager.active_page` raises `RuntimeError` if no active page / no session
- Playwright lifecycle managed in `BrowserManager.start_session()/stop_session()` — browser + playwright stopped on shutdown
- `tools/__init__.py` registers all 20 tools via module list — adding a tool means creating a file and adding it to `_TOOL_MODULES`
- `VALID_OS` in `config.py` validates target OS against `{windows, linux, macos}`
- `profile` is required on every `navigate` call — no ephemeral sessions
- S3 is **required**: all four `CAMOUFOX_S3_*` vars must be set; missing any raises `RuntimeError` on first `navigate`
- Profile uses a `TemporaryDirectory` per session as `user_data_dir`; pulled from S3 on start, pushed on stop, temp dir deleted after push
- `profile_store.pull_profile()` creates an empty local dir when S3 returns 404/NoSuchKey
- `profile_store.push_profile()` never deletes the profile dir — temp dir cleanup is `BrowserManager.stop_session()`'s responsibility
- S3 profile key format: `profiles/<name>.zip`
- Addons are downloaded once (`.xpi` cached in `~/.cache/camoufox-mcp/addons/`), extracted fresh to a temp dir per session, cleaned up on `stop_session()`
- `CAMOUFOX_ADDON_URLS` env var overrides default addon list; empty string disables all addons
- `ConsoleMonitor` + `NetworkMonitor` attach per `PageHandle`; bounded deque (max 1000 entries); reset on navigation, bodies fetched on-demand
- `PageHandle` captures the latest dialog via `page.on("dialog")` — one pending dialog stored (last wins); cleared after `respond_to_dialog()`
- `uid_selector()` in `dom/uid.py` is the single source for `data-mcp-uid` CSS selectors

## E2E Test Suite

60 tests using `pytest-asyncio` + in-memory `fastmcp.Client`. Flask test server + moto S3 server auto-start per session.

- `tests/conftest.py` — `_s3_mock` (session-scoped, autouse: starts `ThreadedMotoServer` on port 5124, sets S3 env vars, creates bucket) + `flask_server` + `client` (per-test, kills session on teardown)
- `tests/helpers.py` — `extract_uid()`, `extract_first_reqid()`, `tool_text()`
- `tests/test_<tool>.py` — One file per tool group (click, fill, evaluate, press_key, scroll, upload, wait_for, dialog, screenshot, snapshot, network, console, infinite_scroll, tools_registered)
- `tests/test_profile.py` — Profile persistence across sessions via moto S3. Manages `Client(mcp)` manually
- `tests/test_profile_s3.py` — S3 unit tests against moto server: pull not-found, pull found (extracts zip), push (zips+uploads), roundtrip, noop on missing dir
- `tests/test_os_fingerprint.py` — OS fingerprint: parametrized over windows/linux/macos
- `tests/server.py` — Flask routes + API endpoints
- `tests/templates/<name>.html` — One template per tool group

All tests pass `"profile": "<name>"` to every `navigate` call. `click` and `fill` auto-scroll elements into view before interaction.

## Adding a New Tool

1. Create `tools/<tool_name>.py` following the existing pattern
2. Import shared helpers from `tools._context`
3. Define `register(mcp: FastMCP)` with one `@mcp.tool()` async function
4. Add the module to `_TOOL_MODULES` list in `tools/__init__.py`
5. Add a test page in `tests/templates/` and route in `tests/server.py`
6. Add `tests/test_<tool>.py` with E2E tests
7. Run `ruff check src/ tests/ && ruff format src/ tests/ && CAMOUFOX_HEADLESS=true pytest`
