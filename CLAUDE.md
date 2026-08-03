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
  server.py     # entrypoint: logging config + main() (stdio or daemon proxy)
  bootstrap.py  # composition root: SERVER_NAME/INSTRUCTIONS, build_deps, build_server, lifespan
  config.py     # ONLY place reading os.environ; frozen ServerConfig
  session_defaults.py  # frozen SessionDefaults dataclass (per-session creation options)
  updater.py    # throttled, non-blocking fail-open auto-update (browser binary + GeoIP)
  telemetry.py  # per-profile JSONL usage logger
  telemetry_intent.py  # evaluate() intent buckets + literal-stripped script fingerprint
  sessions/     # SessionManager, Session, launch kwargs, PageBook, Page wrapper, monitors
  dom/          # UID snapshot system + JS injection (evaluated via Page.evaluate)
  tools/        # one file per tool; _base.py (@tool + get_session/get_page), _errors.py
                # (error rendering), _observe.py (observation), _text.py (render/truncate)
  daemon/       # opt-in shared daemon: main/routes, proxy, spawn, lifecycle (TTL), identity,
                # errors, endpoint (POSIX UDS vs Windows loopback+token strategy), auth (token gate)
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
- Tools never raise out. The `@tool` wrapper (via `tools/_errors.py`) converts every
  exception to a **one-line** `"Error: <Type>: <msg>"` (or `"Timeout: <msg>"` for
  `TimeoutError`): the Playwright "Call log:" tail is stripped and newlines folded,
  and Playwright's bare `Error` class renders as `PlaywrightError` (never
  `Error: Error:`). A tool body is pure happy-path returning a `str`. Do not wrap
  tool bodies in try/except for the generic case.
- `screenshot` is still the sole image tool, but returns `[note, Image]` (not a bare
  `Image`) when `max_width` scaling applies — the note carries the click_at
  coordinate multiplier. All other tools return `str`.
- Never return `page.raw` or any raw Playwright object in tool output.
- `from __future__ import annotations` at the top of every module.
- Files stay under 300 lines — split along domain boundaries, never compress.
- Profiles are **local only** — no S3/cloud sync. `<data_dir>/profiles/<profile>/`
  is a persistent Playwright context reused across sessions with the same name.

## Conventions

- `config.py` is the only place calling `os.getenv` — everything else reads
  `deps.config`. The sole exception is `daemon/spawn.py` passing `os.environ.copy()`
  to the detached daemon subprocess, which re-derives its own `ServerConfig`.
- Session-creation options (`fingerprint_os`, `viewport_width`, `viewport_height`,
  `locale`, `block_images`, `block_webrtc`, `headless`) apply only when a profile
  session is first created; silently ignored on an already-active profile.
- `fingerprint_os` must be validated against `camoufox_mcp.config.VALID_OS`
  (`{"windows", "linux", "macos"}`) — raise `ValueError` otherwise.
- `click`/`fill` take `uid` XOR `selector` (exactly one; both/neither raises); the
  selector path is Playwright-native (`locator(selector).first`).
- `observe: 'none'|'snapshot'|'text'` on `click`/`click_at`/`fill`/`navigate` appends
  a post-action observation to the string result, via the shared `tools/_observe.py`
  helper (validate once at the top of the body). `'screenshot'` is deliberately not a
  mode — it would break the sole-image-tool invariant.
- `scroll` moves the viewport via `window.scrollBy` (evaluate), not `mouse.wheel`,
  which is inert on headless Camoufox/Firefox.
- Stale/unknown uid: `raise ValueError(f"unknown or stale uid '{uid}'; take a new
  snapshot")` — the wrapper renders the exact mandated error string.
- `ProfileInUseError` (from `camoufox_mcp.sessions`) is raised by
  `SessionManager.get_or_create` when another OS process holds the profile lock;
  the wrapper renders `"Error: ProfileInUseError: profile '<p>' is locked by
  another process"`.
- Telemetry (JSONL, one line per tool call) is fully automatic via `@tool` — never
  log manually. Beyond the base fields (ts, profile, tool, truncated args,
  duration_ms, ok, error, result note) each record now carries measurability fields:
  `result_chars`, `url`, screenshot `img_w/img_h/img_bytes/est_image_tokens`, and
  evaluate `intent/script_hash/script_len`. Lifecycle markers: `server_start`
  (config snapshot, proxy redacted) in `_server.jsonl`, `session_closed` per profile
  on shutdown.

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
- Startup auto-update is fail-open AND non-blocking: `ensure_browser_present`
  only blocks on a cold install (no binary at all); the version check + refresh
  run in a background task, throttled to once per 24h via a stamp file. So
  concurrent server starts never stall on the GitHub check.
- `CAMOUFOX_HEADLESS` unset defaults to a visible window, which needs a working
  desktop GL stack; `virtual` (Xvfb) is the reliable invisible mode and what the
  E2E suite exercises alongside `true`. `virtual` is **Linux-only** — Xvfb does not
  exist on Windows/macOS, so `build_launch_kwargs` raises `ValueError` there; use
  `true`. `virtual` mutates the **process-global** `DISPLAY`, so never mix visible
  and virtual sessions in one process.
- Daemon is **opt-in** (`CAMOUFOX_DAEMON=true`); with it unset the code path is
  byte-identical to before. The proxy runs no auto-update, telemetry, or
  `SessionManager` — those live only in the daemon. Its TTL exits **only** at zero
  active sessions AND zero in-flight requests (never evicts a live session); the
  identity check is `version` + `code_path` (idle mismatch respawns, live-session
  mismatch is reused with a warning).
- The daemon's control channel is abstracted by `daemon/endpoint.py` (`ENDPOINT`
  singleton chosen at import by `os.name`): POSIX serves over a `0o600` Unix socket;
  Windows serves over a `127.0.0.1` loopback socket whose only access boundary is a
  per-daemon bearer token (`daemon/auth.py`), advertised with `{host, port, token}`
  in a `0o600` `daemon.endpoint` file. The spawn lock is `filelock`, the detached
  spawn uses `start_new_session` (POSIX) or `DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP`
  (Windows), and self-terminate raises `SIGTERM` in-process on Windows (an `os.kill`
  there would be an abrupt TerminateProcess). Keep POSIX behavior untouched when
  editing this layer.

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
- Network HTTP/SSE transport — the client-facing transport is stdio only; the
  daemon's internal HTTP runs over a private Unix socket (POSIX) or a token-guarded
  loopback socket (Windows), never a routable TCP port.
- PyPI distribution — GitHub install only (`uvx --from git+...` or clone).
- Cloud/S3 profile sync — profiles are local-disk only.
- Session TTL / auto-eviction — sessions close only via explicit `close_session`;
  the daemon TTL shuts the daemon down but never closes a live session.
