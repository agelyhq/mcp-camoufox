# 🏗️ Architecture

A FastMCP stdio server. An MCP client spawns it as a subprocess and talks JSON-RPC
over stdin and stdout. It is never a network service.

```
src/camoufox_mcp/
  server.py            entry point: logging setup and main()
  bootstrap.py         composition root: server name, instructions, dependencies, lifespan
  config.py            the only module that reads os.environ; frozen ServerConfig
  proxy_url.py         both directions of a proxy URL: parsing and redaction, in 1 place
  session_defaults.py  frozen dataclass of per-session creation options
  updater.py           throttled, non-blocking, fail-open auto-update
  telemetry.py         per-profile JSONL logger (+ telemetry_intent.py for evaluate)
  profile_name.py      the filename-safe rule, imported by both consumers of a name
  deadlines.py         bounded(): the one way to await a Playwright call under a clock
  sessions/            SessionManager, Session, launch kwargs, PageBook, Page, monitors,
                       the log both monitors are built from, teardown, stdio silencing
  dom/                 element identity: registry (the handle), identity, capture,
                       actions, waiting (the poll), scripting, errors, source
  dom/js/              numbered bundle concatenated in order: boot, visibility, names,
                       walk, selector, query, geometry, actions, ops. Never names this
                       project.
  tools/               one file per tool, plus the @tool decorator, telemetry record,
                       error rendering, observation, settled observation, page line,
                       target resolution and text helpers
  daemon/              optional shared daemon: proxy, spawn, lifecycle, routes, recovery,
                       the endpoint abstraction with its unix and loopback strategies,
                       socket path, identity, auth
```

Dependencies point inward: `tools/` uses `sessions/` and `dom/`, which use `config.py`.
Nothing points back out. `dom/` in particular must not import from `sessions/`; it
works against a small protocol (`RegistryPage`, anything owning an `.elements` store),
which is why it can be tested and reasoned about without a browser.

## 🗂️ Sessions

`SessionManager` is the only owner of live sessions. Nothing launches at startup: the
first tool call for a profile name takes a `filelock`, launches a persistent Camoufox
context at `<data_dir>/profiles/<name>/`, and keeps it until `close_session` or process
exit. Launches are serialised per profile, never process-wide, so one cold multi-second
start does not hold up the first call of every other client. Closing is bounded at every
step: a tab that stops answering Juggler is abandoned rather than allowed to hang the
shutdown behind it.

The console and network monitors are one type twice. Both are a `PreservingLog`: a
bounded ring of the current document's entries, a second ring holding what the previous
document left behind, and a rotation driven by the tab's own navigations. Only the main
frame counts as one, since a page whose ad or captcha iframe navigates has not itself gone
anywhere, and treating that as a navigation used to empty the live ring under the agent.

Which entries a rotation retires is the monitor's decision, not the ring's, because the
commit and the requests do not share a source: the document request and the sub-resources
it leads to are announced by the browser's HTTP layer, the commit by the content process
hosting the new document. A cold session's first navigation spawns that process, so on a
loaded machine the commit lands after the page's own load-time fetch has been captured
(measured here: 50 to 380 ms after, on 5 of 6 cold navigations under CPU contention).
Retiring the whole ring then discarded requests belonging to the document the caller was
asking about, and `list_network_requests` answered "No network requests captured." for a
page whose fetch had already been answered 200. So the network monitor retires by entry
id: everything recorded after a navigation's own document request was asked for by the
document that request delivered. Only the tab's own main-frame document requests are
candidates, since Firefox announces an embed's document under the same `document`
resource type and a boundary taken from one of those lands in the middle of the current
document's life. Of the candidates the boundary is the FIRST since the last rotation, not
the latest, because a redirect chain and a navigation superseded before it committed both
leave 2 outstanding, and the commit that lands belongs to only 1 of them. A navigation
carrying no document request of the tab's own (`about:blank`, a `data:` URL, a
same-document history move) retires the whole ring, and so does every console rotation: a
message carries no evidence of its document, and needs none, since messages and commits
are both announced by the content process.

`Page.raw` is the single escape hatch to Playwright, and it is restricted to the surface
verified to leave no trace in the page: `mouse`, `keyboard`, `screenshot`, `goto` and
`wait_for_load_state`. Banned repo-wide: `locator()`, `query_selector`,
`wait_for_selector`, `wait_for_function`, every `page.<action>(selector, ...)` form, and
every `ElementHandle` action method.

The ban has 2 independent reasons, both measured rather than assumed:

- Every one of those calls dispatches `CustomEvent("__playwright_mark_target__")` onto the
  target element before acting. It bubbles, it is composed, and any page catches it with a
  single listener and no polling.
- Creating an `ElementHandle` at all instantiates Playwright's injected script in the
  page's own realm. Measured: 13 listeners appear on `window`, the first of them
  `__playwright_global_listeners_check__`, plus 1 `MutationObserver`.

Element actions therefore go through `page.elements`, and every screenshot passes
`caret="initial"` so Playwright stops writing `caret-color: transparent` inline onto every
field before capturing.

Tools never touch Playwright any other way, and never return a raw Playwright object.

## 🏷️ The uid system

`snapshot` walks the visible DOM with ARIA-aware heuristics (roles, `aria-label`,
`<label for>`, computed accessible names) and mints an `eN` uid for every interactive
element. It is a DOM traversal, not the browser's own accessibility tree, and it covers
the top document only, so iframes and shadow roots are out of reach today.

**Nothing is written to the page.** The uid table is a plain JavaScript object living in
the tab's own heap, created once per document and reachable only through a single
`JSHandle` held on the Python side. Its remote type is `object` and never `node`, which is
precisely what keeps Playwright's injected script out of the page. It holds a map from uid
to a `WeakRef`, with a `WeakMap` from element back to uid as the identity index, so
nothing we do pins a removed node in memory.

A uid therefore names an **element**, not a position. An element still present in the next
capture keeps the uid it already had, whatever moved around it, and the counter only ever
goes up so a retired number is never reissued. Because the table dies with its execution
context, a cross-document navigation renumbers for free, while a same-document history
change preserves every uid. That is the only renumbering, and it needs no navigation hook.

The price is that uid numbers carry no document-order meaning: a capture can legitimately
render `e0 e1 e57 e2`. Recovering ordering would mean renumbering, which is exactly the
recycling bug this design exists to remove.

A uid that no longer resolves produces exactly:

```
Error: ValueError: unknown or stale uid 'e12'; take a new snapshot
```

That covers an unknown or malformed uid, a detached element, a table rebuilt by
navigation, and a dead execution context. A closed tab is a different thing and stays
`TargetClosedError`: telling an agent to re-snapshot a browser that is gone would be an
unbounded retry loop.

Selectors are resolved by our own engine rather than Playwright's, for the same reason:
plain CSS through the browser's native `querySelectorAll`, plus 2 extensions,
`:has-text("...")` and `text=...`, which together covered every non-CSS selector in the
measurement window. A selector list is resolved per comma branch and unioned in document
order, so `.a, .b:has-text("x")` means what it reads as. Any other special syntax raises
an error naming what is supported, rather than silently matching nothing. Note the engine
prefixes are refused only at the start of a selector, so `[role="button"]` and
`[data-testid="x"]` are ordinary CSS and work.

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

The wrapper binds the call's arguments once and does everything that depends on the
tool's own name from there: the post-action observation an `observe` argument asked
for, then the `[page]` line. A body that appended either would restate a name the
wrapper already knows, which is how the two drift apart. A tool that needs more in its
telemetry record declares it at registration (`@tool(mcp, deps, analytics=...)`)
instead of the wrapper testing for it.

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
