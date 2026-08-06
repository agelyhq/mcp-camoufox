# CLAUDE.md: mcp-camoufox

## Purpose

A FastMCP **stdio** server exposing browser-automation tools backed by **Camoufox**
(anti-detect Firefox, driven through Playwright's async API).

Product thesis in order: (1) **sites do not block it**, the reason anyone installs it;
(2) **sign in once by hand, reuse the profile forever**; (3) **mandatory per-profile
isolation**. The rest is table stakes.

Never argue on tool-surface size: that debate is not ours to win, and the real argument is
anti-detection. Never mimic CDP semantics blindly; use the Camoufox, Firefox and Playwright
native way. Never name another project outside `docs/isolation.md`, and every claim there
must survive that project's maintainer reading it.

## Architecture

`src/camoufox_mcp/`: `server.py` (entrypoint), `bootstrap.py` (composition root, holds
`SERVER_INSTRUCTIONS`), `config.py` (the only reader of `os.environ`), `updater.py`,
`telemetry.py`, `profile_name.py`, `deadlines.py` (`bounded()`), then `sessions/`, `dom/`
with its numbered `dom/js/` bundle, `tools/` (one file per tool), and the opt-in
`daemon/`. File-by-file map in `docs/architecture.md`.

Dependencies point inward: `tools/` uses `sessions/` and `dom/`, which use `config.py`.
`tools/` never touches Playwright except through `page.raw`.

Repo root holds only `README.md`, `CLAUDE.md`, `LICENSE` and build/config files; every
other document lives in `docs/`. `README.md` is the shop window (hook, install,
differentiators, credits), never grows a reference section, and names no other project.
`docs/decisions.md` records what we will NOT do, so those debates stay closed.

## Boundaries

- One public tool per file in `tools/`. File exports `def register(mcp, deps) -> None` and
  registers exactly one handler via `@tool(mcp, deps)`; never add `@mcp.tool` too. First
  positional param is `profile: str`, except `list_sessions` which takes none and logs to
  `_server.jsonl`. `deps: ToolDeps` (frozen: `config`, `sessions`, `telemetry`) is injected
  at registration via closure; never read `ctx.lifespan_context` for it.
- Tools never raise out. The `@tool` wrapper (`tools/_errors.py`) converts every exception
  to a **one-line** `"Error: <Type>: <msg>"` (`"Timeout: <msg>"` for `TimeoutError`):
  Playwright's "Call log:" tail stripped, newlines folded, bare `Error` rendered as
  `PlaywrightError`. Tool bodies are pure happy path returning `str`; no generic
  try/except. An off-contract exception type also leaves a full traceback in the server
  log, which is how the 133-occurrence `UnicodeDecodeError` went unexplained for a month.
- `screenshot` is the sole image tool; it returns `[note, Image]` when `max_width` scaling
  applies (the note carries the click_at multiplier). All others return `str`, never a raw
  Playwright object.
- `from __future__ import annotations` everywhere; files under 300 lines (split, never
  compress); profiles are local-disk only, never synced. Tests drive the public surface: a
  seam a test needs is a public name, never a monkeypatched `_underscored` one.

## Conventions

- `config.py` is the only place calling `os.getenv`; everything else reads `deps.config`.
  Sole exception: `daemon/spawn.py` hands the detached subprocess a copy of the
  environment, and it re-derives its own `ServerConfig`.
- Session-creation options apply only at a profile's first launch and are ignored on an
  active one. `navigate` resolves them into the frozen `SessionInitOptions` that
  `get_or_create` takes, so no keyword travels untyped.
- `click`/`fill` take `uid` XOR `selector`, resolved through `tools/_target.py` so the
  rule and its wording live in 1 place. Both paths converge: a selector is polled until a
  match is visible, gets a uid, and the uid path takes over.
- Closed sets of accepted words go through `_errors.validate_choice` before any side effect.
- `observe` is appended by the `@tool` wrapper, never by a tool body, and capped at 4000
  chars in both modes so an appendix cannot outweigh the action. `'screenshot'` is
  deliberately not a mode: it would break the sole-image-tool invariant.
- `scroll` uses `window.scrollBy`, not `mouse.wheel`, which is inert on headless Firefox.
- Two mandated error strings, rendered verbatim by the wrapper: `unknown or stale uid
  '<uid>'; take a new snapshot`, and `ProfileInUseError: profile '<p>' is locked by another
  process`. Profile names are validated before they reach a path: `profile_name.py`.
- Telemetry is automatic via `@tool`; never log manually. A tool needing more than the
  shared fields declares a hook at registration rather than the wrapper testing for a name.
  Reference in `docs/telemetry.md`.

## Invariants

- `tools/__init__.py` auto-discovers modules via `pkgutil` and calls each
  `register(mcp, deps)`, so parallel additions never merge-conflict over a list. A module
  without `register` raises at startup: a composition defect must not quietly shrink the
  advertised surface.
- `SessionManager` is the only owner of live `Session` objects, created lazily on first
  use and never at startup. Launching locks per profile, never process-wide, and every
  teardown step runs under `deadlines.bounded` so a wedged tab cannot hang the exit.
- The per-tab monitors rotate on the tab's own navigations, **main frame only**, and the
  network one **by entry id**: the commit comes from the content process while requests come
  from the HTTP layer, so a new document's fetch can sit in the ring, answered, before the
  commit lands. Either wholesale rotation empties a listing an agent was about to read.
- **Nothing we do is written to the page.** `Page.raw` is restricted to `mouse`,
  `keyboard`, `screenshot`, `goto`, `wait_for_load_state`; `screenshot` must pass
  `caret="initial"`; `evaluate_handle` may only ever build the registry object. Banned
  repo-wide: `locator()`, `query_selector`, `wait_for_selector`, `wait_for_function`,
  `page.<action>(selector, ...)`, every `ElementHandle` action. Both reasons are measured
  in `docs/architecture.md`. Guarded by `tests/test_no_markers.py`, whose probes
  (`tests/probes.py`) are proved able to detect each signal before asserting its absence,
  refuse a document the parser has not finished, name every mutation's target, and run with
  no extension at all: Camoufox ships uBlock Origin unless `CAMOUFOX_BUNDLED_ADDONS=false`.
- No `await` in injected JS: `page.evaluate` has no deadline at any layer and a page can
  replace `Promise`. Every op is one synchronous turn, bounded from Python. No file under
  `dom/js/` may name this project: a page hooking `window.eval` reads that source verbatim.
- Every built-in the bundle calls is captured in `B` at boot, and no bundle file may use
  `for...of` or an `Array.prototype` method: both resolve on the page's own prototypes at
  call time, so a page replacing one counts every element we examine. Collect with
  `out[out.length] = x`. Keep the `00_boot.js` comment honest about what it does NOT cover.
  Guarded by `tests/test_dom_layering.py` and `tests/test_observability_boundary.py`.
- A uid names 1 element in 1 tab and 1 document: it survives a re-render there, and any
  other tab or document refuses it. Numbers carry no document order. A closed tab raises
  `TargetClosedError`, never the stale-uid string.
- `dom/` takes any page-protocol object, importing neither `sessions/` types nor Playwright.
- Startup auto-update is fail-open AND non-blocking: only a cold install blocks, the version
  check runs in a background task throttled to 24h, and never writes inside site-packages.
- `humanize` is opt-in and off by default: a missed `hit-renderer` ack wedges a
  process-global dispatch chain with no timeout, measured at 2,004,856 ms in production.
  When set it must reach Camoufox as a **float**: `bool` subclasses `int`, "not a double".
- `CAMOUFOX_HEADLESS` unset means a visible window (needs desktop GL); `virtual` (Xvfb) is
  the reliable invisible mode, **Linux-only**, and each launch gets its own `env` so the
  modes coexist. `CAMOUFOX_BROWSER_VERSION` pins the build; unset, the launcher chases
  upstream, which is how this project silently moved 1 Firefox major.
- Daemon is opt-in (`CAMOUFOX_DAEMON=true`); unset, the code path is byte-identical to
  single-process mode. The proxy owns no auto-update, telemetry or `SessionManager`. TTL
  exits only at zero sessions AND zero in-flight requests. `daemon/endpoint.py` abstracts
  the channel, `endpoint_unix.py` and `endpoint_loopback.py` implement it. Every exit is a
  signal that uvicorn re-raises, so NOTHING after `run_http_async` runs, `finally` included:
  cleanup goes in `lifecycle.cleanup_on_termination`. An advert is removed only by its
  proven owner, proof taken at `bind()`. Details in `docs/daemon.md`.

## Build / lint / test

`make install`, `make lint` (must exit 0), `make format`, `make test` (real Camoufox plus a
local Flask, offline), `make run`. The only CI is `.github/workflows/release.yml`: a version
tag builds, refuses a tag disagreeing with the built version, runs the WHOLE suite on the
runner, then publishes through OIDC behind a manual approval. Lint is not in it, it runs
here. The runner covers **3.12 and 3.13**, both `requires-python` accepts, because a 3.13
stdlib behaviour once satisfied an assertion our own code owed; `make test-oldest` runs 3.12
locally. **No test may wait a duration before asserting**: wait for the
appearance, deadline as guardrail, via `tests/waits.py:poll_until`. Shared test code lives
only in `tests/`; `tools/list` is budgeted in `tests/payload_baseline.json`.

## Out of scope

CDP/V8-only capabilities (heap snapshots, Chrome tracing, Lighthouse, screencast,
throttling), client-facing transport (stdio only), cloud profile sync, session TTL, iframe
and shadow-root uids. Argued in `docs/decisions.md`: point there, do not re-litigate.

## License

**FSL-1.1-MIT**, source-available, not open source. Never reintroduce plain-MIT wording in
`LICENSE` or `pyproject.toml` (`license = "LicenseRef-FSL-1.1-MIT"`), and never drop
`docs/CONTRIBUTING.md`, whose contributor grant keeps relicensing possible. The README
carries no License section: it is a shop window, not a legal notice.
