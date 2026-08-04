# CLAUDE.md: mcp-camoufox

## Purpose

A FastMCP **stdio** server exposing browser-automation tools backed by
**Camoufox** (anti-detect Firefox, driven via Playwright's async API).

Product thesis in order: (1) **sites do not block it**, the reason anyone installs
it; (2) **sign in once by hand, reuse the profile forever**; (3) **mandatory
per-profile isolation**. The rest is table stakes competitors also have.

Never frame this as a "drop-in replacement for chrome-devtools-mcp": comparing tool
surfaces invites a debate we lose (they have more, and a better page model), and the
real argument is anti-detection. Never mimic CDP semantics blindly; use the
Camoufox/Firefox/Playwright native way. Claims about competitors must survive a
maintainer reading them, see `docs/isolation.md` for the verified wording.

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

Repo root holds only `README.md`, `CLAUDE.md`, `LICENSE` and build/config files;
every other document lives in `docs/` (index, getting-started, profiles, anti-bot,
isolation, tools, configuration, daemon, telemetry, architecture, decisions,
CONTRIBUTING, CHANGELOG). `README.md` is the shop window (hook, install,
differentiators, comparison, credits) and never grows a reference section.
`docs/decisions.md` records what we will NOT do, so those debates stay closed.

## Boundaries

- One public tool per file in `tools/`. File exports `def register(mcp, deps) -> None`
  and registers exactly one handler via `@tool(mcp, deps)`; never add `@mcp.tool` too.
- Every tool's first positional param is `profile: str` (required), except
  `list_sessions` which has none (logs to `_server.jsonl`).
- `deps: ToolDeps` (frozen dataclass: `config`, `sessions`, `telemetry`) is injected
  at registration via closure; never read `ctx.lifespan_context` for it.
- Tools never raise out. The `@tool` wrapper (`tools/_errors.py`) converts every
  exception to a **one-line** `"Error: <Type>: <msg>"` (`"Timeout: <msg>"` for
  `TimeoutError`): Playwright's "Call log:" tail stripped, newlines folded, bare
  `Error` rendered as `PlaywrightError`. Tool bodies are pure happy path returning
  `str`; no generic try/except.
- `screenshot` is the sole image tool; it returns `[note, Image]` when `max_width`
  scaling applies (the note carries the click_at multiplier). All others return `str`,
  and never a raw Playwright object.
- `from __future__ import annotations` everywhere; files under 300 lines (split, never
  compress); profiles are local-disk only, never synced.

## Conventions

- `config.py` is the only place calling `os.getenv`; everything else reads
  `deps.config`. Sole exception: `daemon/spawn.py` passes `os.environ.copy()` to the
  detached subprocess, which re-derives its own `ServerConfig`.
- Session-creation options (`fingerprint_os`, `viewport_width`, `viewport_height`,
  `locale`, `block_images`, `block_webrtc`, `headless`) apply only when a profile
  session is first created; silently ignored on an already-active profile.
- `fingerprint_os` must be validated against `camoufox_mcp.config.VALID_OS`
  (`{"windows", "linux", "macos"}`); raise `ValueError` otherwise.
- `click`/`fill` take `uid` XOR `selector` (exactly one; both/neither raises); the
  selector path is Playwright-native (`locator(selector).first`).
- `fill` on a `<select>` picks an option instead of typing: `dom/actions.py` reads the
  options in JS (`select_options.js`), matches on value, then label, then label
  case-insensitively, and raises listing the available options when nothing matches.
  Do NOT import Playwright exceptions into `dom/` to do this; the layer stays
  Playwright-free apart from `page.raw`.
- `snapshot` surfaces a form control's `<label for>` text as `label=<text>`: without
  it a `<select>` with no `name` or `placeholder` is untargetable by its visible name.
- `observe: 'none'|'snapshot'|'text'` on `click`/`click_at`/`fill`/`navigate` appends
  a post-action observation via `tools/_observe.py` (validate once at the top of the
  body). `'screenshot'` is deliberately not a mode: it would break the sole-image-tool
  invariant.
- `scroll` uses `window.scrollBy` (evaluate), not `mouse.wheel`, which is inert on
  headless Camoufox/Firefox.
- Two mandated error strings, rendered verbatim by the wrapper: `unknown or stale uid
  '<uid>'; take a new snapshot`, and `ProfileInUseError: profile '<p>' is locked by
  another process` (raised by `SessionManager.get_or_create`).
- Telemetry (JSONL, one line per tool call) is fully automatic via `@tool`; never
  log manually. Records carry measurability fields (`result_chars`, `url`, screenshot
  `est_image_tokens`, evaluate `intent`/`script_hash`) plus `server_start` and
  `session_closed` markers. Field-by-field reference in `docs/telemetry.md`.

## Invariants

- `tools/__init__.py` auto-discovers modules via `pkgutil` and calls each
  `register(mcp, deps)`; no hardcoded tool list, so parallel additions never
  merge-conflict there.
- `SessionManager` is the only owner of live `Session` objects; a profile session
  is created lazily on first `navigate`/`get_or_create` call, never at startup.
- `Page.raw` is the only Playwright-native escape hatch (hover, drag, keyboard,
  `set_input_files`, `select_option`, `wait_for_selector`, `goto`, history nav).
- `dom/` functions take any object satisfying `EvaluatablePage` (`.evaluate`);
  they must not import `sessions/` types directly.
- Startup auto-update is fail-open AND non-blocking: `ensure_browser_present`
  only blocks on a cold install (no binary at all); the version check + refresh
  run in a background task, throttled to once per 24h via a stamp file. So
  concurrent server starts never stall on the GitHub check.
- `humanize` is opt-in via `CAMOUFOX_HUMANIZE` and off by default: it intermittently
  wedges Firefox mid-`Page.dispatchMouseEvent` so the call never returns (rationale in
  `docs/decisions.md`). When set it must reach Camoufox as a **float**: `bool`
  subclasses `int`, and `humanize:maxTime = true` is rejected as "not a double".
- `CAMOUFOX_HEADLESS` unset means a visible window (needs desktop GL). `virtual`
  (Xvfb) is the reliable invisible mode and is **Linux-only** (`build_launch_kwargs`
  raises `ValueError` elsewhere). It mutates the **process-global** `DISPLAY`, so
  never mix visible and virtual sessions in one process.
- Daemon is opt-in (`CAMOUFOX_DAEMON=true`); unset, the code path is byte-identical
  to single-process mode. The proxy owns no auto-update, telemetry or
  `SessionManager`. TTL exits only at zero sessions AND zero in-flight requests.
  Its control channel is abstracted by `daemon/endpoint.py` (POSIX `0o600` UDS vs
  Windows loopback + bearer token); keep POSIX behavior untouched when editing it.
  Full details in `docs/daemon.md`.

## Build / lint / test

`make install` (uv sync), `make lint` (ruff check + format --check, must exit 0),
`make format`, `make test` (real Camoufox + local Flask, offline), `make run`.
No CI exists: `make lint` and `make test` are run by hand before a release.

## Out of scope

CDP/V8-only capabilities (heap snapshots, Chrome tracing, Lighthouse, screencast,
throttling), client-facing network transport (stdio only), cloud profile sync, and
session TTL. Each one is argued in `docs/decisions.md`: point at
that file rather than re-litigating them in review.

## License

**FSL-1.1-MIT**, source-available, not open source: free for any use including
internal commercial use, forbids shipping it inside a competing commercial product,
auto-converts to MIT 2 years per release. Licensor: Agely / Fabien Vauchelles.
Never reintroduce plain-MIT wording in `LICENSE` or `pyproject.toml`
(`license = "LicenseRef-FSL-1.1-MIT"`). `docs/CONTRIBUTING.md` carries the contributor
grant that keeps relicensing possible, so it must not be dropped. The README does not
carry a License section: it is a shop window, not a legal notice.
