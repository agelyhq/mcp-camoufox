# mcp-camoufox

A FastMCP **stdio** server exposing browser-automation tools backed by
[Camoufox](https://camoufox.com) — anti-detect Firefox, driven through
Playwright's async API.

## Purpose

A drop-in replacement for `chrome-devtools-mcp` in Claude Code, but on
Firefox/Camoufox, with **per-profile session isolation**: every tool takes a
mandatory `profile` name, and each profile gets its own dedicated Camoufox
browser + persistent on-disk context. Multiple concurrent Claude Code
conversations (or terminal tabs) never cross-talk — profile `"alice"` and
profile `"bob"` are fully independent browsers with independent
cookies/localStorage.

Design principle: this project does **not** mimic Chrome/CDP semantics
blindly. Where Camoufox/Firefox/Playwright work differently from
`chrome-devtools-mcp`, it embraces their native way, and it exploits Camoufox
strengths that Chrome doesn't have: anti-detect fingerprinting, GeoIP-aware
proxy handling, and humanized cursor movement.

## Tech Stack

- **Python 3.12+**
- **FastMCP 3.x** — MCP framework, stdio transport
- **Camoufox** (`camoufox[geoip]`) — anti-detect Firefox, wraps Playwright
- **Playwright async API** — page/browser control under the hood
- **platformdirs** — OS-appropriate data/log directories
- **filelock** — cross-process profile locking
- **uv** — dependency management

## Architecture

```
src/camoufox_mcp/
  server.py     # composition root: FastMCP instance, lifespan, auto-update, run stdio
  config.py     # only place reading os.environ; frozen ServerConfig
  session_defaults.py  # frozen SessionDefaults dataclass (per-session creation options)
  updater.py    # fail-open auto-update (browser binary + GeoIP) via camoufox's own API
  telemetry.py  # per-profile JSONL usage logger
  sessions/     # SessionManager, Session, launch kwargs, PageBook, Page wrapper, monitors
  dom/          # UID snapshot system + JS injection (accessibility-tree based targeting)
  tools/        # one file per tool; _base.py has the @tool decorator + get_session/get_page
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
| `navigate` | `profile, url, [fingerprint_os, viewport_width, viewport_height, locale, block_images, block_webrtc], timeout?` | Lazily creates the session on first call; navigates. Creation-only options are ignored (with a note) on an already-active profile. |
| `reload` | `profile` | Reload the current page. |
| `go_back` | `profile` | Navigate back in history. |
| `go_forward` | `profile` | Navigate forward in history. |
| `wait_for` | `profile, condition, selector?, timeout?` | Wait for `load`, a CSS `selector`, or `network_idle`. |

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
| `snapshot` | `profile` | Accessibility-tree text dump; assigns `eN` uids to interactive elements — the core interaction primitive. |
| `screenshot` | `profile, full_page?, uid?` | PNG image; whole viewport, full page, or cropped to a uid's bounding box. |
| `get_html` | `profile, outer_html?` | Live post-JS `outerHTML` (default) or `<body>` `innerHTML`. |

### Interaction

| Tool | Key params | Description |
|---|---|---|
| `click` | `profile, uid, double_click?` | Click an element by uid. |
| `click_at` | `profile, x, y, double_click?` | Click raw viewport coordinates — for canvas/no-uid targets. |
| `hover` | `profile, uid` | Hover an element by uid. |
| `drag` | `profile, from_uid, to_uid` | Drag from one element to another. |
| `fill` | `profile, uid, value, clear_first?` | Clear (default) and type a value into a field. |
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
- **HTTP/SSE transport** — stdio only; this server is meant to be spawned
  as a subprocess by an MCP client, not exposed as a network service.
- **Cloud/S3 profile sync** — profiles are local-disk only.

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `CAMOUFOX_HEADLESS` | unset → visible window | `true` (headless) / `virtual` (Xvfb, Linux only) / `false` (visible) |
| `CAMOUFOX_PROXY` | (none) | `http://user:pass@host:port` — parsed into a Playwright proxy dict; forces `geoip=True` |
| `CAMOUFOX_DATA_DIR` | `platformdirs.user_data_dir("camoufox-mcp")` | Base directory for profiles + logs |
| `CAMOUFOX_FINGERPRINT_OS` | random | Default fingerprint OS: `windows` / `linux` / `macos` |
| `CAMOUFOX_VIEWPORT` | Camoufox default | e.g. `1280x720` |
| `CAMOUFOX_LOCALE` | Camoufox default | Default browser locale, e.g. `en-US` |
| `CAMOUFOX_ADDON_URLS` | built-in default addons | Comma-separated override list of addon URLs |
| `CAMOUFOX_AUTO_UPDATE` | `true` | Set `false` to disable the startup browser/GeoIP auto-update check |
| `CAMOUFOX_BINARY` | Camoufox's own cache | Explicit path to a Camoufox executable |

`CAMOUFOX_HEADLESS`, session-creation options, and startup behavior are
env-only — they are not per-tool parameters (except the `navigate`
creation-only overrides listed in the Tools section above, which win over the
env defaults for a brand-new profile).

## Install

No PyPI package — install straight from GitHub.

**Run directly with `uvx`:**

```bash
uvx --from git+https://github.com/agelyhq/mcp-camoufox camoufox-mcp
```

**Or clone and install locally:**

```bash
git clone git@github.com:agelyhq/mcp-camoufox.git
cd mcp-camoufox
make install
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

## Local testing

```bash
git clone git@github.com:agelyhq/mcp-camoufox.git
cd mcp-camoufox
make install
make test    # CAMOUFOX_HEADLESS=true uv run pytest — real Camoufox + a local Flask
             # server serving tests/templates/*.html, no Internet access needed
make run     # uv run camoufox-mcp — starts the stdio server directly
```

Tests use an in-memory `fastmcp.Client(mcp)` against the real tool set and a
real (headless) Camoufox browser — nothing browser-side is mocked.

## Build / lint / test

```bash
make install   # uv sync --extra dev
make lint      # ruff check . + ruff format --check .  (must exit 0)
make format    # ruff format . + ruff check --fix .
make build     # uv sync --no-dev
make test      # CAMOUFOX_HEADLESS=true uv run pytest
make clean     # remove .venv, caches, build artifacts
```

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
- `ok` / `error` — `false` and `"<Type>: <message>"` on failure, else `true` / `null`.
- `result` — short human-readable note of the outcome.

Logging is best-effort: a logging failure never breaks a tool call.
