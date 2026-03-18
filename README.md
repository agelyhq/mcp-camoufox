# Camoufox MCP

MCP server for [Camoufox](https://github.com/daijro/camoufox) anti-detect browser. Gives AI agents full browser control — navigate, click, fill forms, take screenshots — through 21 MCP tools. Built with [FastMCP](https://gofastmcp.com/).

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Installation

Install directly from the GitHub repo with `uv`:

```bash
uv tool install git+ssh://git@github.com/agelyhq/mcp-camoufox.git
```

The Camoufox browser binary is **downloaded automatically** on first run — no manual `camoufox fetch` needed.

> **Private repo access**: Requires SSH key registered with GitHub. Alternatively, use HTTPS with a [personal access token](https://github.com/settings/tokens):
> ```bash
> uv tool install git+https://<TOKEN>@github.com/agelyhq/mcp-camoufox.git
> ```

### Upgrade

```bash
uv tool upgrade camoufox-mcp
```

## Usage

### Windsurf / Cursor

Add to your MCP config (e.g. `~/.codeium/windsurf/mcp_config.json`):

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/agelyhq/mcp-camoufox.git", "camoufox-mcp"],
      "env": {
        "CAMOUFOX_HEADLESS": "true",
        "CAMOUFOX_S3_ENDPOINT": "https://s3.gra.io.cloud.ovh.net",
        "CAMOUFOX_S3_ACCESS_KEY": "<your-access-key>",
        "CAMOUFOX_S3_SECRET_KEY": "<your-secret-key>",
        "CAMOUFOX_S3_BUCKET": "<your-bucket>",
        "CAMOUFOX_S3_REGION": "gra"
      }
    }
  }
}
```

> `uvx` handles venv creation, dependency installation, and binary fetch automatically.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/agelyhq/mcp-camoufox.git", "camoufox-mcp"],
      "env": {
        "CAMOUFOX_HEADLESS": "true",
        "CAMOUFOX_S3_ENDPOINT": "https://s3.gra.io.cloud.ovh.net",
        "CAMOUFOX_S3_ACCESS_KEY": "<your-access-key>",
        "CAMOUFOX_S3_SECRET_KEY": "<your-secret-key>",
        "CAMOUFOX_S3_BUCKET": "<your-bucket>",
        "CAMOUFOX_S3_REGION": "gra"
      }
    }
  }
}
```

### Run standalone

```bash
camoufox-mcp
```

The server communicates via stdio — connect any MCP client.

## Session Lifecycle

The browser starts **lazily** on the first `navigate` call — no explicit start tool needed.

1. **`navigate`** — Pass a URL and a **required** `profile` name. If no session is running, one starts automatically. Session params (OS, viewport, etc.) are accepted and used only on first start.
2. Use browser tools (`click`, `fill`, `take_snapshot`, …) as needed.
3. **`kill_session`** — Kill the browser, reset everything. The next `navigate` starts a fresh session.

Only one session can run at a time. GeoIP spoofing and humanized interactions are always enabled.

### Persistent Profiles

A `profile` name is **required** on every `navigate` call. S3 must be configured — profile storage requires it.

On session start, the profile zip is downloaded from S3 into a temp directory (created fresh if not found). On `kill_session`, the profile is zipped, uploaded back to S3, and the temp directory is deleted.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CAMOUFOX_HEADLESS` | `true` | Headless mode (`true`/`false`) |
| `CAMOUFOX_PROXY` | — | Proxy URL (server-level, not per-session) |
| `CAMOUFOX_BINARY` | _(auto)_ | Custom Camoufox binary path |
| `CAMOUFOX_ADDON_URLS` | _(defaults)_ | Comma-separated addon `.xpi` URLs. Defaults to [I still don't care about cookies](https://addons.mozilla.org/firefox/addon/istilldontcareaboutcookies/). Set to empty string to disable all addons |
| `CAMOUFOX_S3_ENDPOINT` | **required** | S3-compatible endpoint URL (e.g. OVH: `https://s3.gra.cloud.ovh.net`) |
| `CAMOUFOX_S3_ACCESS_KEY` | **required** | S3 access key |
| `CAMOUFOX_S3_SECRET_KEY` | **required** | S3 secret key |
| `CAMOUFOX_S3_BUCKET` | **required** | S3 bucket name for profile storage |
| `CAMOUFOX_S3_REGION` | `us-east-1` | S3 region (OVH example: `gra`) |

> All four `CAMOUFOX_S3_*` variables must be set. Without them, `navigate` will fail with a clear error.

## Available Tools

| Tool | Description |
|---|---|
| `navigate` | Go to a URL — **`profile` is required**; auto-starts browser on first call |
| `kill_session` | Kill the browser, upload profile to S3, reset everything |
| `take_snapshot` | Text tree of page with element UIDs |
| `take_screenshot` | PNG screenshot |
| `click` | Click element by UID |
| `fill` | Type into input by UID |
| `press_key` | Keyboard key or combo (`Enter`, `Control+a`) |
| `scroll` | Scroll page or element into view |
| `wait_for` | Wait for load / CSS selector / idle |
| `evaluate` | Run JavaScript |
| `get_content` | Get page HTML |
| `get_page_info` | List open tabs |
| `select_page` | Switch active tab |
| `new_page` | Open new tab |
| `close_page` | Close tab |
| `handle_dialog` | Accept/dismiss browser dialogs |
| `upload_file` | Upload file through file input |
| `list_console_messages` | List captured browser console messages (errors, warnings, logs) |
| `list_network_requests` | List captured network requests |
| `get_network_request` | Get full details of a network request |

## Development

```bash
git clone git@github.com:agelyhq/mcp-camoufox.git
cd mcp-camoufox
uv sync --extra dev
```

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### Running Tests

E2E tests use `pytest` with an in-memory FastMCP client and a Flask test server:

```bash
# Run all tests (headless)
CAMOUFOX_HEADLESS=true uv run pytest

# Run a specific test file
CAMOUFOX_HEADLESS=true uv run pytest tests/test_click.py -v

# Run with visible browser (useful for debugging)
uv run pytest tests/test_click.py -v
```

### Test Server

A Flask server with dedicated pages for testing each MCP tool:

```bash
python tests/server.py
# Serves at http://127.0.0.1:5123
```

| Page | URL | Tools covered |
|---|---|---|
| Click | `/click` | `click` (single, double, checkbox, radio) |
| Fill | `/fill` | `fill` (text, email, textarea, contenteditable, select) |
| Evaluate | `/evaluate` | `evaluate` (data attributes, JS globals, JSON) |
| Press Key | `/press-key` | `press_key` (arrows, combos, key log) |
| Scroll | `/scroll` | `scroll` (10 colored sections) |
| Upload | `/upload` | `upload_file` (uploads to server, returns file info) |
| Wait For | `/wait-for` | `wait_for` (elements appear at 3s, 5s, 8s) |
| Dialog | `/dialog` | `handle_dialog` (alert, confirm, prompt) |
| Screenshot | `/screenshot` | `take_screenshot` (colorful, scrollable) |
| Snapshot | `/snapshot` | `take_snapshot` (varied ARIA roles) |
| Network | `/network` | `list_network_requests`, `get_network_request` (AJAX) |
| Console | `/console` | `list_console_messages` (log, warn, error) |
| Infinite Scroll | `/infinite-scroll` | `scroll`, `wait_for`, `list_network_requests` |
