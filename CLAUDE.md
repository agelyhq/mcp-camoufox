# CLAUDE.md — mcp-camoufox

## Purpose

A FastMCP **stdio** server exposing browser-automation tools backed by
**Camoufox** (anti-detect Firefox, driven via Playwright's async API). A
drop-in replacement for `chrome-devtools-mcp` in Claude Code, but on
Firefox/Camoufox, with **per-profile session isolation** so multiple
concurrent Claude Code conversations never cross-talk. Design principle: do
NOT mimic Chrome/CDP semantics blindly — embrace Camoufox/Firefox/Playwright's
native way and exploit Camoufox strengths (fingerprinting, geoip, humanize).

## Architecture

```
src/camoufox_mcp/
  server.py     # composition root: FastMCP instance, lifespan, auto-update, run stdio
  config.py     # ONLY place reading os.environ; frozen ServerConfig
  session_defaults.py  # frozen SessionDefaults dataclass (per-session creation options)
  updater.py    # fail-open auto-update (browser binary + GeoIP) via camoufox programmatic API
  telemetry.py  # per-profile JSONL usage logger
  sessions/     # SessionManager, Session, launch kwargs, PageBook, Page wrapper, monitors
  dom/          # UID snapshot system + JS injection (evaluated via Page.evaluate)
  tools/        # one file per tool; _base.py has the @tool decorator + get_session/get_page
```

Dependencies point inward: `tools/` → `sessions/` + `dom/` → `config.py`.
`tools/` never touches Playwright directly except through `page.raw`.

## Boundaries

- One public tool per file in `tools/`. File exports `def register(mcp, deps) -> None`
  and registers exactly one handler via `@tool(mcp, deps)` — never add `@mcp.tool` too.
- Every tool's first positional param is `profile: str` (required), except
  `list_sessions` which has none (logs to `_server.jsonl`).
- `deps: ToolDeps` (frozen dataclass: `config`, `sessions`, `telemetry`) is injected
  at registration via closure — never read `ctx.lifespan_context` for it.
- Tools never raise out. The `@tool` wrapper converts every exception to
  `"Error: <Type>: <msg>"` (or `"Timeout: <msg>"` for `TimeoutError`), so a tool body
  is pure happy-path returning a `str` (or `Image` for `screenshot`, the sole
  non-string tool). Do not wrap tool bodies in try/except for the generic case.
- Never return `page.raw` or any raw Playwright object in tool output.
- `from __future__ import annotations` at the top of every module.
- Files stay under 300 lines — split along domain boundaries, never compress.
- Profiles are **local only** — no S3/cloud sync. `<data_dir>/profiles/<profile>/`
  is a persistent Playwright context reused across sessions with the same name.

## Conventions

- `config.py` is the only place calling `os.getenv` — everything else reads
  `deps.config`.
- Session-creation options (`fingerprint_os`, `viewport_width`, `viewport_height`,
  `locale`, `block_images`, `block_webrtc`) apply only when a profile session is
  first created; silently ignored on an already-active profile.
- `fingerprint_os` must be validated against `camoufox_mcp.config.VALID_OS`
  (`{"windows", "linux", "macos"}`) — raise `ValueError` otherwise.
- Stale/unknown uid: `raise ValueError(f"unknown or stale uid '{uid}'; take a new
  snapshot")` — the wrapper renders the exact mandated error string.
- `ProfileInUseError` (from `camoufox_mcp.sessions`) is raised by
  `SessionManager.get_or_create` when another OS process holds the profile lock;
  the wrapper renders `"Error: ProfileInUseError: profile '<p>' is locked by
  another process"`.
- Telemetry (JSONL, one line per tool call: ts, profile, tool, truncated args,
  duration_ms, ok, error, result note) is fully automatic via `@tool` — never log
  manually inside a tool body.

## Invariants

- `tools/__init__.py` auto-discovers modules via `pkgutil` and calls each
  `register(mcp, deps)` — no hardcoded tool list, so parallel additions never
  merge-conflict there.
- `SessionManager` is the only owner of live `Session` objects; a profile session
  is created lazily on first `navigate`/`get_or_create` call, never at startup.
- `Page.raw` is the only Playwright-native escape hatch (hover, drag, keyboard,
  `set_input_files`, `select_option`, `wait_for_selector`, `goto`, history nav).
- `dom/` functions take any object satisfying `EvaluatablePage` (`.evaluate`) —
  they must not import `sessions/` types directly.
- Startup auto-update is fail-open: if the browser binary is stale but update
  fails, start anyway with a local binary if one exists; hard-fail only if none
  exists at all.

## Build / lint / test

```
make install   # uv sync --extra dev
make lint      # ruff check . + ruff format --check . (must exit 0)
make format    # ruff format . + ruff check --fix .
make test      # CAMOUFOX_HEADLESS=true uv run pytest (real Camoufox + local Flask, no Internet)
make run       # uv run camoufox-mcp
```

## Out of scope

- Any CDP/V8-only capability: heap snapshots, Chrome tracing, Lighthouse audits,
  screencast, CPU throttling. Camoufox is Firefox-based — these have no equivalent
  and are deliberately not emulated.
- HTTP/SSE transport — stdio only.
- PyPI distribution — GitHub install only (`uvx --from git+...` or clone).
- Cloud/S3 profile sync — profiles are local-disk only.
- Session TTL / auto-eviction — sessions close only via explicit `close_session`.
