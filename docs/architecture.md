# 🏗️ Architecture

A FastMCP stdio server. An MCP client spawns it as a subprocess and talks JSON-RPC
over stdin and stdout. It is never a network service.

```
src/camoufox_mcp/
  server.py            entry point: logging setup and main()
  bootstrap.py         composition root: server name, instructions, dependencies, lifespan
  config.py            the only module that reads os.environ; frozen ServerConfig
  session_defaults.py  frozen dataclass of per-session creation options
  updater.py           throttled, non-blocking, fail-open auto-update
  telemetry.py         per-profile JSONL logger
  telemetry_intent.py  evaluate() intent buckets and script fingerprinting
  sessions/            SessionManager, Session, launch kwargs, PageBook, Page, monitors
  dom/                 uid snapshot system and the JS it injects
  tools/               one file per tool, plus the @tool decorator and error rendering
  daemon/              optional shared daemon: proxy, spawn, lifecycle, routes, endpoint
```

Dependencies point inward: `tools/` uses `sessions/` and `dom/`, which use `config.py`.
Nothing points back out. `dom/` in particular must not import from `sessions/`; it
works against a small protocol (`EvaluatablePage`, anything with `.evaluate`), which is
why it can be tested and reasoned about without a browser.

## 🗂️ Sessions

`SessionManager` is the only owner of live sessions. Nothing launches at startup: the
first tool call for a profile name takes a `filelock`, launches a persistent Camoufox
context at `<data_dir>/profiles/<name>/`, and keeps it until `close_session` or process
exit.

`Page.raw` is the single escape hatch to Playwright. Hover, drag, keyboard,
`set_input_files`, `select_option`, `wait_for_selector`, `goto` and history navigation
go through it. Tools never touch Playwright any other way, and never return a raw
Playwright object.

## 🏷️ The uid system

`snapshot` walks the visible DOM with ARIA-aware heuristics (roles, `aria-label`,
`<label for>`, focusability) and stamps `data-mcp-uid="eN"` on interactive elements.
It is a DOM traversal, not the browser's own accessibility tree, and it covers the top
document only, so iframes and shadow roots are out of reach today.

Later calls address elements by that uid, resolved back through a
`[data-mcp-uid="eN"]` selector.

Uids are valid until the next navigation or snapshot. A stale one produces exactly:

```
Error: ValueError: unknown or stale uid 'e12'; take a new snapshot
```

The stamp is a real DOM attribute rather than an in-memory map, which means it
survives anything that keeps the element alive, and dies with the element. There is no
cache to go quietly wrong.

## 🧰 Tools

One public tool per file. Each file exports `register(mcp, deps)` and registers exactly
one handler through the `@tool` decorator. `tools/__init__.py` discovers modules with
`pkgutil` and calls each `register`, so there is no hardcoded list, and 2 people
adding tools in parallel never conflict over an index file.

`deps` is a frozen dataclass (`config`, `sessions`, `telemetry`) injected at
registration through a closure. Tools do not reach into the lifespan context for it.

Tools never raise. The `@tool` wrapper converts every exception into a one-line
`Error: <Type>: <message>`, stripping Playwright's call-log tail and folding newlines.
A tool body is therefore pure happy path returning a string. It also emits the
telemetry record, which is why no tool logs by hand.

## 🔄 Startup and auto-update

Fail-open and non-blocking. `ensure_browser_present` blocks only on a cold install
where there is no binary at all. The version check and refresh run in a background
task, throttled to once per 24 hours through a stamp file, so concurrent server starts
never queue behind a GitHub request and a network failure never prevents startup.

## 🧪 Testing

Full scenarios through the MCP surface, not unit tests of internals. The suite runs an
in-memory `fastmcp.Client` against the real tool set, a real Camoufox browser, and a
local Flask server serving `tests/templates/*.html`. Nothing browser-side is mocked
and no internet access is needed.

Every test is bounded by `pytest-timeout` at 180 seconds, using the thread method
because Windows has no `SIGALRM`. Without it, a browser dying mid-call leaves the
in-flight request waiting for a reply that never comes and the run hangs forever
instead of failing.

## 📏 Constraints

- Files stay under 300 lines. Over that, split along a domain boundary.
- `from __future__ import annotations` at the top of every module.
- Typed errors with useful messages. Nothing swallowed silently.
