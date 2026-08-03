# mcp-camoufox

A FastMCP **stdio** server exposing browser-automation tools backed by
[Camoufox](https://camoufox.com) — anti-detect Firefox, driven through
Playwright's async API.

## Purpose

A drop-in replacement for `chrome-devtools-mcp` in Claude Code, but on
Firefox/Camoufox, with **per-profile session isolation**: every tool takes a
mandatory `profile` name, and each profile gets its own dedicated Camoufox
browser + persistent on-disk context, so concurrent Claude Code conversations
never cross-talk.

Design principle: never mimic Chrome/CDP semantics blindly — embrace the
Camoufox/Firefox/Playwright native way and exploit Camoufox strengths Chrome
lacks: anti-detect fingerprinting, GeoIP-aware proxies, humanized cursor.

## Tech Stack

- **Python 3.12+**
- **Linux, macOS, Windows** — the stdio server and the optional daemon run on all
  three; only `CAMOUFOX_HEADLESS=virtual` (Xvfb) is Linux-only
- **FastMCP 3.x** — MCP framework, stdio transport (plus HTTP over a Unix domain
  socket on POSIX, or a token-authenticated loopback socket on Windows, for the
  optional daemon proxy)
- **Camoufox** (`camoufox[geoip]`) — anti-detect Firefox, wraps Playwright
- **Playwright async API** — page/browser control under the hood
- **Pillow** — optional screenshot downscaling (`max_width`)
- **platformdirs** — OS-appropriate data/log directories
- **filelock** — cross-process profile locking
- **uv** — dependency management

Camoufox and Playwright are version-bounded together (`camoufox<0.5`,
`playwright<1.59`): an unbounded transitive Playwright once drifted ahead of the
installed Camoufox binary's Juggler protocol schema and every launch failed with a
`Browser.setDefaultViewport` error, so the two are pinned to move in lockstep.

## Architecture

```
src/camoufox_mcp/
  server.py     # entrypoint: logging config + main() (stdio or daemon proxy)
  bootstrap.py  # composition root: server name/instructions, build_deps, build_server, lifespan
  config.py     # only place reading os.environ; frozen ServerConfig
  session_defaults.py  # frozen SessionDefaults dataclass (per-session creation options)
  updater.py    # throttled, non-blocking fail-open auto-update (browser binary + GeoIP)
  telemetry.py  # per-profile JSONL usage logger
  telemetry_intent.py  # evaluate() intent buckets + literal-stripped script fingerprint
  sessions/     # SessionManager, Session, launch kwargs, PageBook, Page wrapper, monitors
  dom/          # UID snapshot system + JS injection (accessibility-tree based targeting)
  tools/        # one file per tool; _base.py has the @tool decorator + get_session/get_page
                # _errors.py (error rendering), _observe.py (observation), _text.py (render/truncate)
  daemon/       # optional shared daemon: main/__main__, proxy, spawn, lifecycle/TTL, routes, identity, errors
```

A profile session is created lazily — nothing launches at startup. The first
tool call against a new `profile` name acquires a lock, launches a persistent
Camoufox context rooted at `<data_dir>/profiles/<profile>/`, and keeps it
alive until `close_session` (or process exit) closes it. The on-disk profile
(cookies, localStorage, etc.) survives across `close_session` / re-navigate
cycles.

Element targeting uses a UID scheme: `snapshot` walks the accessibility tree
and stamps `data-mcp-uid="eN"` on interactive elements; subsequent tools
(`click`, `fill`, `hover`, ...) address elements by that uid. UIDs are valid
until the next navigation or snapshot.

## Tools

All tools take `profile: str` as the first argument (mandatory session
isolation key), except `list_sessions`. Every tool returns a plain string on
success and `"Error: <Type>: <message>"` (or `"Timeout: <message>"`) on
failure — except `screenshot`, the sole tool that returns an image.

### Session

| Tool | Key params | Description |
|---|---|---|
| `list_sessions` | — | List active profiles with page count, current URL/title per tab. |
| `close_session` | `profile` | Close the browser for a profile; the on-disk profile is kept. |

### Navigation

| Tool | Key params | Description |
|---|---|---|
| `navigate` | `profile, url, [fingerprint_os, viewport_width, viewport_height, locale, block_images, block_webrtc, headless], observe?, timeout?` | Lazily creates the session on first call; navigates. Creation-only options (including `headless: true/false/virtual`) are ignored (with a note) on an already-active profile. `observe: none/snapshot/text` appends a post-navigation observation. |
| `reload` | `profile` | Reload the current page. |
| `go_back` | `profile` | Navigate back in history. |
| `go_forward` | `profile` | Navigate forward in history. |
| `wait_for` | `profile, condition, selector?, expression?, return_expression?, timeout?` | Wait for `load`, a CSS `selector`, `network_idle`, or `predicate` (a JS `expression` re-checked each frame). `return_expression` is evaluated once after any successful wait and appended. |

### Tabs

| Tool | Key params | Description |
|---|---|---|
| `list_pages` | `profile` | List open tabs (index, title, url, active flag). |
| `new_page` | `profile, url?` | Open a new tab, optionally navigating it; becomes active. |
| `close_page` | `profile, page_idx` | Close a tab by index. |
| `select_page` | `profile, page_idx` | Make a tab active by index. |

### Inspection

| Tool | Key params | Description |
|---|---|---|
| `snapshot` | `profile, max_nodes?, interactive_only?` | Accessibility-tree text dump; assigns `eN` uids to interactive elements — the core interaction primitive. `max_nodes` (default 1500) caps the tree with a well-formed truncation note; `interactive_only` drops structural leaves. |
| `screenshot` | `profile, full_page?, uid?, max_width?` | PNG image; whole viewport, full page, or cropped to a uid's bounding box. `max_width` downscales wider captures and returns `[note, image]` (the note carries the coordinate multiplier for `click_at`). |
| `get_html` | `profile, selector?, max_chars?, strip_scripts?, mode?` | Live post-JS markup or text. `selector` scopes to the first match; `mode='html'` (default `outerHTML`, scripts stripped) or `'text'` (`innerText`); capped at `max_chars` (default 20000, `<=0` unlimited). |

### Interaction

| Tool | Key params | Description |
|---|---|---|
| `click` | `profile, uid \| selector, double_click?, observe?` | Click an element; provide exactly one of `uid` or a CSS `selector`. `observe: none/snapshot/text` appends a post-action observation. |
| `click_at` | `profile, (x, y) \| points, double_click?, observe?` | Click raw viewport coordinates — for canvas/no-uid targets. `points: [[x,y], ...]` clicks a batch sequentially. `observe` appends once, after the last click. |
| `hover` | `profile, uid` | Hover an element by uid. |
| `drag` | `profile, from_uid, to_uid` | Drag from one element to another. |
| `fill` | `profile, uid \| selector, value, clear_first?, observe?` | Clear (default) and type a value; provide exactly one of `uid` or a CSS `selector`. `observe` appends a post-action observation. |
| `fill_form` | `profile, fields` | Batch-fill: `fields = [{uid, value}, ...]`. |
| `type_text` | `profile, text, submit?` | Type into the currently focused element; optional trailing Enter. |
| `press_key` | `profile, key` | Send a keyboard key (e.g. `Enter`, `Control+A`). |
| `scroll` | `profile, direction, amount?, uid?` | Scroll the page, or scroll a uid element into view. |
| `upload_file` | `profile, uid, file_path` | Set a file input's value. |
| `handle_dialog` | `profile, action, prompt_text?` | Accept or dismiss a pending `alert`/`confirm`/`prompt` dialog. |

### Scripting

| Tool | Key params | Description |
|---|---|---|
| `evaluate` | `profile, script` | Run JS in page context; returns a JSON-serialized result. |

### Network

| Tool | Key params | Description |
|---|---|---|
| `list_network_requests` | `profile, resource_types?, page_size?, page_idx?, include_preserved?` | Paginated request/response log for the active tab. |
| `get_network_request` | `profile, reqid, max_body_size?` | Full detail (headers, body) for one request by id. |

### Console

| Tool | Key params | Description |
|---|---|---|
| `list_console_messages` | `profile, levels?, limit?` | Recent console messages, optionally filtered by level. |

### Performance

| Tool | Key params | Description |
|---|---|---|
| `performance_summary` | `profile` | W3C Navigation + Resource Timing summary (DNS/connect/TTFB/DOMContentLoaded/load, resource count and total transfer size, breakdown by initiator type). Firefox-native, no CDP. |

## Out of scope

Deliberately excluded — Camoufox is Firefox-based and these are inherently
CDP/V8-only capabilities with no Firefox equivalent:

- **Heap snapshots** (`take_heapsnapshot`) — V8-specific memory profiling.
- **Chrome performance tracing** (`performance_start_trace` / `_stop_trace` /
  `_analyze_insight`) — the CDP trace format doesn't exist on Firefox;
  `performance_summary` covers the same ground via standard W3C Timing APIs.
- **Lighthouse audits** — depends on Chrome's CDP-driven auditing pipeline.
- **Screencast / CPU-throttling / device emulation presets** — CDP session
  features without a Playwright/Firefox equivalent worth faking.
- **Network HTTP/SSE transport** — the client-facing transport is stdio only;
  this server is spawned as a subprocess by an MCP client, never exposed on a TCP
  port. The optional daemon (below) talks HTTP over a private Unix domain socket
  (POSIX) or a token-guarded `127.0.0.1` loopback socket (Windows), never a routable
  network service.
- **Cloud/S3 profile sync** — profiles are local-disk only.

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `CAMOUFOX_HEADLESS` | unset → visible window | `true` (headless) / `virtual` (Xvfb, **Linux only** — rejected at launch on Windows/macOS, use `true` there) / `false` (visible). A visible window needs a working desktop GL stack; on Linux, when in doubt use `virtual` (invisible, best anti-detection). |
| `CAMOUFOX_PROXY` | (none) | `http://user:pass@host:port` — parsed into a Playwright proxy dict; forces `geoip=True` |
| `CAMOUFOX_DATA_DIR` | `platformdirs.user_data_dir("camoufox-mcp")` | Base directory for profiles + logs |
| `CAMOUFOX_FINGERPRINT_OS` | random | Default fingerprint OS: `windows` / `linux` / `macos` |
| `CAMOUFOX_VIEWPORT` | Camoufox default | e.g. `1280x720`. Keep it small (~`1000x700`) for localhost dev loops — screenshots are billed by pixel count and are the #1 token sink, so a smaller window directly cuts image cost. |
| `CAMOUFOX_LOCALE` | Camoufox default | Default browser locale, e.g. `en-US` |
| `CAMOUFOX_ADDON_URLS` | built-in default addons | Comma-separated override list of addon URLs |
| `CAMOUFOX_AUTO_UPDATE` | `true` | Set `false` to disable the startup browser/GeoIP auto-update check |
| `CAMOUFOX_BINARY` | Camoufox's own cache | Explicit path to a Camoufox executable |
| `CAMOUFOX_DAEMON` | `false` | Set `true` to route the stdio entry through a shared local daemon (see below). Default path is unchanged. |
| `CAMOUFOX_DAEMON_TTL` | `1800` | Daemon idle self-shutdown timeout in seconds (only meaningful when `CAMOUFOX_DAEMON=true`). |

`CAMOUFOX_HEADLESS`, session-creation options, and startup behavior are
env-only — they are not per-tool parameters (except the `navigate`
creation-only overrides listed in the Tools section above — including `headless`
— which win over the env defaults for a brand-new profile).

## Shared daemon mode (opt-in)

By default every stdio process launches and owns its own browsers. Set
`CAMOUFOX_DAEMON=true` to instead turn the `camoufox-mcp` entry point into a **thin
proxy** to a single local **daemon** that owns all browsers, so multiple concurrent
Claude Code conversations share one set of sessions, one auto-update, and one
process. Profile isolation is unchanged — it is still keyed by `profile` name.

- **What it does.** The proxy forwards every MCP call to the daemon (FastMCP proxy
  over a persistent backend session). Auto-update, telemetry, and the
  `SessionManager` live only in the daemon; the proxy owns none of them.
- **Lifecycle.** The first proxy to start spawns the daemon detached (under a spawn
  lock, with stale-socket cleanup and a `/health` readiness poll). Crash recovery is
  v1: the daemon is only ensured at proxy startup, so a daemon that dies
  mid-conversation is not respawned until the next conversation starts. For
  debugging, run it in the foreground with `camoufox-mcp-daemon` (or
  `python -m camoufox_mcp.daemon`).
- **Transport.** The proxy reaches the daemon over a private HTTP control channel,
  bound before uvicorn starts by the platform `daemon/endpoint.py` strategy:
  - **POSIX** — a Unix domain socket at `<data_dir>/daemon/daemon.sock` (uvicorn
    `uds`; client via httpx). Its parent `<data_dir>/daemon/` (which also holds the
    spawn lock and log) is created `0o700`, so the socket is never world-reachable
    during the brief window before it is itself tightened to `0o600` right after bind.
  - **Windows** — a `127.0.0.1` loopback socket on an ephemeral port (asyncio has no
    Unix-socket server there). Since any local process can reach loopback, every
    request must carry a per-daemon bearer token; the daemon advertises
    `{host, port, token}` in a `0o600` `<data_dir>/daemon/daemon.endpoint` file, and
    `TokenAuthMiddleware` rejects any unauthenticated request. The spawn lock is a
    cross-platform `filelock`.
- **TTL.** The daemon self-terminates after `CAMOUFOX_DAEMON_TTL` seconds (default
  1800) but **only** when there are zero active sessions AND zero in-flight
  requests — it never evicts live browsers to hit the timeout.
- **Code-reload / identity.** The daemon advertises its `version` and `code_path` on
  `/health`. A proxy whose code differs shuts down and respawns an **idle**
  mismatched daemon; a mismatched daemon that still holds **live sessions** is
  reused with a warning and never killed. The proxy caches no stale tool lists, so a
  code reload is picked up on the next idle respawn.

The default path (`CAMOUFOX_DAEMON` unset) is byte-identical to single-process mode.

## Install

No PyPI package — install straight from GitHub:

```bash
uvx --from git+https://github.com/agelyhq/mcp-camoufox camoufox-mcp   # run directly
# or: git clone git@github.com:agelyhq/mcp-camoufox.git && cd mcp-camoufox && make install
```

### MCP client configuration (stdio)

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/agelyhq/mcp-camoufox", "camoufox-mcp"],
      "env": {
        "CAMOUFOX_HEADLESS": "true"
      }
    }
  }
}
```

For a local clone, replace `command`/`args` with `"command": "uv", "args":
["run", "--directory", "/path/to/mcp-camoufox", "camoufox-mcp"]`.

## Build / lint / test

```bash
make install   # uv sync --extra dev
make lint      # ruff check . + ruff format --check .  (must exit 0)
make format    # ruff format . + ruff check --fix .
make build     # uv sync --no-dev
make test      # CAMOUFOX_HEADLESS=true uv run pytest
make run       # uv run camoufox-mcp — starts the stdio server directly
make clean     # remove .venv, caches, build artifacts
```

The `Makefile` targets assume a POSIX shell; on Windows run the underlying `uv`
commands directly (`uv sync --extra dev`, `uv run ruff check .`, `uv run pytest`).
The `virtual`-display E2E cases self-skip when `Xvfb` is absent (i.e. everywhere but
Linux).

Tests use an in-memory `fastmcp.Client(mcp)` against the real tool set and a real
(headless) Camoufox browser plus a local Flask server serving
`tests/templates/*.html` — nothing browser-side is mocked, no Internet needed.

Every test is bounded by `pytest-timeout` (180s, `thread` method — `signal` would
need a `SIGALRM` that Windows lacks). Without it a browser dying mid-call leaves the
in-flight MCP request awaiting a reply that never arrives, and the run hangs forever
instead of failing; the timeout dumps every thread's stack so the culprit is visible.

## Telemetry / logs

Every tool call appends one JSON object per line to a per-profile log file:
`<data_dir>/logs/<profile>.jsonl`. Tools without a profile (`list_sessions`)
log to `<data_dir>/logs/_server.jsonl`.

```json
{"ts": "2026-07-15T12:00:00.000Z", "profile": "alice", "tool": "click", "args": {"uid": "e3"}, "duration_ms": 42.7, "ok": true, "error": null, "result": "Clicked e3"}
```

- `ts` — ISO-8601 UTC timestamp.
- `args` — tool arguments, truncated (long strings capped, file bytes elided).
- `duration_ms` — wall-clock call duration.
- `ok` / `error` — `false` and a one-line `"<Type>: <message>"` on failure (the
  Playwright call log is stripped), else `true` / `null`.
- `result` — short human-readable note of the outcome (truncated at 200 chars).
- `result_chars` — full pre-truncation length of a string result.
- `url` — best-effort active-page URL at call time (never creates a session).
- `img_w` / `img_h` / `img_bytes` / `est_image_tokens` — on `screenshot` records;
  the PNG's pixel dimensions, byte size, and an estimated image-token cost
  (`min(ceil(w*h/750), 1568)`), so image spend is measurable.
- `intent` / `script_hash` / `script_len` — on `evaluate` records; a coarse intent
  bucket (`click`/`state`/`style`/`wait`/`read`/`other`), a literal-stripped script
  fingerprint, and the raw script length.

Two lifecycle markers are also emitted: a `server_start` record (config snapshot,
proxy redacted to scheme+host) in `_server.jsonl`, and a
`session_closed(reason=shutdown)` record per profile when the server shuts down.

Logging is best-effort: a logging failure never breaks a tool call.
