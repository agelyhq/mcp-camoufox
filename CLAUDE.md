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
`SERVER_INSTRUCTIONS`), `config.py` (the only reader of `os.environ`), `updater/`,
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

- `config.py` is the only reader of `os.environ`; everything else reads `deps.config`. A
  subprocess (the daemon, the fetch child) gets `config.child_env()`, a copy it re-derives its
  own `ServerConfig` from, so no spawner reads the environment itself.
- Session-creation options apply at a profile's first launch only; `navigate` resolves them
  into the frozen `SessionInitOptions` `get_or_create` takes, so no keyword travels untyped.
- `click`/`fill` take `uid` XOR `selector`, resolved through `tools/_target.py` so the rule and
  its wording live in 1 place: a selector is polled until visible, gets a uid, and converges.
- Closed sets of accepted words go through `_errors.validate_choice` before any side effect.
- `observe` is appended by the `@tool` wrapper, never by a tool body, and capped at 4000 chars
  in both modes; `'screenshot'` is not a mode: it would break the sole-image-tool invariant.
- `scroll` uses `window.scrollBy`, not `mouse.wheel`, which is inert on headless Firefox.
- Two mandated error strings, rendered verbatim by the wrapper: `unknown or stale uid
  '<uid>'; take a new snapshot`, and `ProfileInUseError: profile '<p>' is locked by another
  process`. Profile names are validated before they reach a path: `profile_name.py`.
- Telemetry is automatic via `@tool`; never log manually. A tool needing more than the shared
  fields declares a hook at registration, not a wrapper name test; `tools/_target_notes.py`
  caps every string it writes. Only `args` is redacted, so no layer may quote a typed value
  into a message and a credential is elided where it is RENDERED: a fill value goes when ANY
  of the field's 4 names looks secret or nothing resolved; `Cookie`/`Authorization` values
  and secret-named POST fields go in `_net_secrets.py`. Reference: `docs/telemetry.md`.

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
  in `docs/architecture.md`. No tab subscribes to `filechooser`: the driver carries that
  event as an `ElementHandle`, whose construction alone installs the injected script (measured,
  `docs/decisions.md`), so a page-driven `input.click()` opens the native dialog and the
  answer is the UPLOADING guidance plus the selector route; `tests/test_driver_footprint.py`
  fails if the subscription returns under any spelling, and pins the `raw` allowlist above
  by reading every `.raw.<attr>` under `src/`. Guarded by `tests/test_no_markers.py`, whose probes
  (`tests/probes.py`) are proved able to detect each signal before asserting its absence,
  refuse a document the parser has not finished, name every mutation's target, and run with
  no extension at all: Camoufox ships uBlock Origin, excluded only when EITHER
  `CAMOUFOX_BUNDLED_ADDONS=false` (server-wide, what the probes use) OR a session was created
  with `block_trackers=false`. The 2 levers are unioned; neither can cancel the other.
- No `await` in injected JS: `page.evaluate` has no deadline at any layer and a page can
  replace `Promise`. Every op is one synchronous turn, bounded from Python. No file under
  `dom/js/` may name this project: a page hooking `window.eval` reads that source verbatim.
- Every built-in the bundle calls is captured in `B` at boot, and no file under `dom/js/` may
  use `for...of` or an `Array.prototype` method: both resolve on the page's own prototypes at
  call time, so a page replacing one counts every element we examine and picks what a read
  returns. Collect with `out[out.length] = x`. Keep `00_boot.js` honest about what it misses.
  Guarded by `tests/test_dom_layering.py` and `tests/test_observability_boundary.py`.
- A uid names 1 element in 1 tab and 1 document: it survives a re-render there, and any
  other tab or document refuses it. Numbers carry no document order. A closed tab raises
  `TargetClosedError`, never the stale-uid string.
- `dom/` takes any page-protocol object, importing neither `sessions/` types nor Playwright.
- Startup auto-update is fail-open AND non-blocking: only a cold install blocks, the version
  check runs in a background task throttled by a 24h stamp that only a completed refresh
  writes, and never writes inside site-packages. Every fetch runs in a child process
  (`updater/child.py` spawns `python -m camoufox_mcp.updater.fetch`, stdin and stdout on the
  null device, a bounded stderr tail as the failure message); the parent keeps the offline
  half (disk reads, activating the pin, the stamp) and terminates the child on shutdown,
  draining stderr while it waits: `Process.wait()` resolves only after every pipe hits EOF,
  and a reader paused on an unread backlog never sees one. The child's own `set_active`
  (camoufox does it on every install) is overridden by the parent re-asserting the pin.
- **This process never assigns `sys.stdout` or `sys.stderr`.** A redirect is process-global
  whichever thread enters it, and fastmcp 4 suspends between our lifespan's `yield` and the
  stdio transport's claim on fd 1: a refresh that swapped the streams from a worker thread in
  that window handed mcp a `StringIO`, and every fresh install died before `initialize` was
  answered. Guarded by `tests/test_no_stream_swaps.py`, whose single exemption is
  `sessions/quiet.py`, around a launch, safe because a session can only be created by a tool
  call, which can only arrive over a transport that already owns fd 1.
- `humanize` is opt-in and off by default: a missed `hit-renderer` ack wedges a
  process-global dispatch chain with no timeout, measured at 2,004,856 ms in production.
  When set it must reach Camoufox as a **float**: `bool` subclasses `int`, "not a double".
- `block_trackers=false`, a `navigate` session-creation option, is the ONLY thing that makes
  this server send `firefox_user_prefs`; it sets no Firefox preference otherwise. Juggler
  pushes them at `Browser.enable`, after startup, onto the USER branch of a persistent
  profile, so Firefox keeps them in `prefs.js`: it is a one-way door for that profile, and
  only its uBO exclusion is per-launch. The 7 measured keys: `launch.py:TRACKER_PREFS_OFF`.
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
local Flask, offline), `make run`. `make build` proves the runtime deps install without the
dev extra, and every target that is not `install` names its environment or its extra: a bare
`uv sync --no-dev` on the shared `.venv` uninstalls pytest and ruff, after which `uv run`
runs a PATH binary against foreign site-packages instead of failing. The only CI is `.github/workflows/release.yml`: a version
tag builds, refuses a tag disagreeing with the built version, runs the WHOLE suite on the
runner, then publishes through OIDC behind a manual approval. Lint is not in it, it runs
here. The runner covers **3.12 and 3.13**, both `requires-python` accepts, because a 3.13
stdlib behaviour once satisfied an assertion our own code owed; `make test-oldest` runs 3.12
locally. `make test-latest` (also in `release.yml`) runs `tests/test_stdio_startup.py` on the
UNLOCKED resolution `uv tool install` gives users: `uv.lock` binds only `uv sync`, fastmcp is
unbounded above, and the 0.4.0 stdio crash reproduced only on fastmcp 4 / mcp 2 while the
locked 3.4.4 / 1.26 stack passed with the bug present. A relock below fastmcp 4 does not
retire that target. **No test may wait a duration before asserting**: wait for the
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
