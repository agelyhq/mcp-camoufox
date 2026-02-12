# AGENTS.md — Camoufox MCP Server

MCP server exposing Camoufox anti-detect browser control to AI agents. Built with [FastMCP](https://gofastmcp.com/). Uses Playwright (via `camoufox` package) for browser lifecycle; custom JS injection for DOM snapshots and UID-based element targeting.

Package: `camoufox_mcp` — dependency: `fastmcp>=2.14`

## Build & Lint

```bash
uv sync --extra dev                    # Install with dev deps
uv run ruff check src/ tests/          # Lint
uv run ruff format src/ tests/          # Format
CAMOUFOX_HEADLESS=true uv run pytest   # Run E2E tests
```

### Quick checks
```bash
uv run ruff check src/camoufox_mcp/tools/   # Lint one package
uv run python -c "from camoufox_mcp.server import mcp"  # Verify imports
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

- **`navigate`** — Auto-starts a session if none is running. Accepts optional `SessionParams` (OS, viewport, profile name, block_images, block_webrtc) used only on first start. GeoIP and humanize are always enabled. Proxy comes from `ServerConfig` (env var).
- **`kill_session`** — Kills browser, clears pages, resets state. Next `navigate` starts fresh. Safe to call when no session is running.
- If `profile` is set, uses `persistent_context=True` + `user_data_dir` resolved under `CAMOUFOX_PROFILES_DIR`.

## Project Structure

- `server.py` — Composition root: FastMCP instance, async lifespan (creates BrowserManager, no browser start), `_ensure_browser_binary()` auto-fetch, entry point
- `browser/addons.py` — Addon lifecycle: download `.xpi` (cached in `~/.cache/camoufox-mcp/addons/`), extract to temp dir per session, cleanup on stop
- `browser/config.py` — `ServerConfig` (env-only: headless, proxy, binary, profiles_dir, addon_urls) + `SessionParams` (per-session: OS, viewport, profile, block flags)
- `browser/manager.py` — `BrowserManager` (lazy Playwright lifecycle, `start_session`/`stop_session` with single-instance guard) + `PageInfo`
- `browser/console.py` — `ConsoleMonitor` + `ConsoleEntry`: captures `page.on("console")` events, bounded deque storage, level filtering, limit-based retrieval
- `browser/network.py` — `NetworkMonitor` + `NetworkEntry`: captures request/response events via Playwright listeners, bounded deque storage, lazy body fetching
- `browser/page_handle.py` — `PageHandle` wraps Playwright `Page` (navigate, evaluate, screenshot, mouse/keyboard, viewport, close, network/console monitors, dialog tracking, file upload)
- `dom/snapshot.py` — JS file loading with dict-based cache
- `dom/uid.py` — `valid_uid()` regex, `uid_selector()` CSS builder, `run_js_action()` shared helper, `resolve_uid()`
- `dom/actions.py` — DOM actions via `run_js_action()`: `clear_field()`, `scroll_into_view()`, `file_input_selector()`
- `js/` — JS files (snapshot, resolve_uid, clear_field, scroll_into_view, file_input_selector) — packaged inside `camoufox_mcp/`
- `tools/_context.py` — `get_manager(ctx)` and `get_page(ctx)` helpers (shared by all tools)
- `tools/navigate.py` — Navigate + lazy session start with optional session params
- `tools/kill_session.py` — Kill browser and reset state
- `tools/list_console_messages.py` — List captured browser console messages with level filtering and limit
- `tools/list_network_requests.py` — List captured network requests with filtering and pagination
- `tools/get_network_request.py` — Get full details (headers, body) of a single request by reqid
- `tools/handle_dialog.py` — Accept or dismiss browser dialogs (alert, confirm, prompt)
- `tools/upload_file.py` — Upload a local file through a file input element via UID
- `tools/list_profiles.py` — List available browser profiles from `CAMOUFOX_PROFILES_DIR`
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
- `tools/__init__.py` registers all 21 tools via module list — adding a tool means creating a file and adding it to `_TOOL_MODULES`
- `VALID_OS` in `config.py` validates target OS against `{windows, linux, macos}`
- Profile names are resolved to `CAMOUFOX_PROFILES_DIR/<name>` — no absolute paths from tool callers
- Addons are downloaded once (`.xpi` cached in `~/.cache/camoufox-mcp/addons/`), extracted fresh to a temp dir per session, cleaned up on `stop_session()`
- `CAMOUFOX_ADDON_URLS` env var overrides default addon list; empty string disables all addons
- `ConsoleMonitor` attaches to each `PageHandle` on construction; bounded deque (max 1000 entries); entries reset on frame navigation with preservation
- `NetworkMonitor` attaches to each `PageHandle` on construction; bounded deque (max 1000 entries); response bodies fetched on-demand via Playwright `Response` reference
- `NetworkMonitor._pending` uses `id(request)` as key — avoids collision when multiple concurrent requests share URL+method
- Network entries reset on frame navigation; previous entries preserved (bounded by `MAX_ENTRIES`)
- `PageHandle` captures the latest browser dialog via `page.on("dialog")` — only one pending dialog stored (last wins); cleared after `respond_to_dialog()`
- `uid_selector()` in `dom/uid.py` is the single source for `data-mcp-uid` CSS selectors — `PageHandle` never builds UID selectors

## E2E Test Suite

58 tests using `pytest-asyncio` + in-memory `fastmcp.Client`. Flask test server auto-starts per session.

- `tests/conftest.py` — `_profiles_dir` (session-scoped, autouse, sets `CAMOUFOX_PROFILES_DIR` before lifespan) + `flask_server` (session-scoped, background thread) + `client` (per-test, kills session on teardown)
- `tests/helpers.py` — `extract_uid()`, `extract_first_reqid()`, `tool_text()`
- `tests/test_<tool>.py` — One file per tool group (click, fill, evaluate, press_key, scroll, upload, wait_for, dialog, screenshot, snapshot, network, console, infinite_scroll, tools_registered)
- `tests/test_profile.py` — Profile persistence (same profile preserves cookies, different profile = independent store) + `list_profiles` tool validation. Manages `Client(mcp)` manually with temp `CAMOUFOX_PROFILES_DIR`
- `tests/test_os_fingerprint.py` — OS fingerprint via local `fingerprint.html` page (CreepJS/FingerprintJS techniques): parametrized over windows/linux/macos, checks detected OS + userAgent; verifies all three produce distinct UAs
- `tests/server.py` — Flask routes + API endpoints
- `tests/templates/fingerprint.html` — Standalone OS fingerprint checker (multi-vector: UA, platform, fonts, WebGL, worker, prototype lies)
- `tests/templates/<name>.html` — One template per tool group

`click` and `fill` tools auto-scroll elements into view before interaction (scroll_into_view + re-resolve coordinates).

## Adding a New Tool

1. Create `tools/<tool_name>.py` following the existing pattern
2. Import shared helpers from `tools._context`
3. Define `register(mcp: FastMCP)` with one `@mcp.tool()` async function
4. Add the module to `_TOOL_MODULES` list in `tools/__init__.py`
5. Add a test page in `tests/templates/` and route in `tests/server.py`
6. Add `tests/test_<tool>.py` with E2E tests
7. Run `ruff check src/ tests/ && ruff format src/ tests/ && CAMOUFOX_HEADLESS=true pytest`
