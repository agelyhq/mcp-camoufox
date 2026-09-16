# 🧭 Decisions

Things this project will not do, and why. Most of these come up as "why not just
add X", so the reasoning lives here instead of being re-litigated in every issue.

## Firefox, not Chrome

Chrome-based automation is easier to build (CDP is a richer protocol than Firefox's
Juggler) and it covers a larger share of real browsing. We still picked Firefox,
because the whole point of the project is the part Chrome cannot give us: Camoufox
patches the browser at the C++ level so the fingerprint is coherent before any page
script runs. A Chrome-based server can inject JS to hide `navigator.webdriver`, but
the injection itself is detectable, and the sites we care about detect it.

Practical consequence: sites that genuinely require Chrome will not work here. In
several months of daily use that has not been a problem, but it is a real trade-off,
not a detail.

## No CDP-only capabilities

These are asked for from time to time and will never exist here, because they are V8 or
CDP features with no Firefox equivalent:

- Heap snapshots (`take_heapsnapshot`): V8-specific memory profiling.
- Chrome performance tracing (`performance_start_trace`, `performance_stop_trace`,
  `performance_analyze_insight`): the CDP trace format does not exist on Firefox, and
  there is no equivalent. This project shipped `performance_summary` for a while as a
  W3C Navigation and Resource Timing report, which is a different and much smaller thing
  than a trace, and it was called 0 times in 8,795 calls. It was removed in 0.3.0. Those
  APIs are still in the page, so `evaluate` reaches them in 1 expression on the rare
  occasion anyone wants them.
- Lighthouse audits: built on Chrome's CDP auditing pipeline.
- Screencast, CPU throttling, device emulation presets: CDP session features with no
  Playwright/Firefox equivalent worth faking.

Emulating these badly would be worse than not having them.

## No `resize_page` or `emulate`

These are the last 2 capabilities a CDP-based server offers that this one does not, once
the V8 and CDP-only ones above are set aside. They will not be implemented as specified.

Camoufox has no equivalent primitive. Window resize is deliberately blocked, and
Playwright's `set_viewport_size` on Firefox moves the content viewport while
`screen.width` and `screen.height` stay at the launch fingerprint. That reintroduces
exactly the viewport-versus-screen mismatch that Camoufox's launch-time coherence
exists to prevent, which is to say it makes the browser detectable again.

The real motivation behind `resize_page` was cutting image tokens, and that is already
served at creation time through `CAMOUFOX_VIEWPORT` or the `viewport_width` and
`viewport_height` arguments of `navigate`.

If this is ever revisited, any viewport lever must be creation-only (rejected on an
active profile) and shrink-only within the launch-fingerprinted screen. Never a live
CDP-style resize.

## 5 tools removed after the measurement

The telemetry work of July 2026 existed to answer one question: which tools does an agent
actually reach for. The window closed on **8,795 real tool calls across 158 profiles over
20 days**, and it settled it.

Removed in 0.3.0: `drag` (0 calls), `go_forward` (0), `performance_summary` (0),
`hover` (1), `type_text` (7).

The earlier argument for keeping everything was that MCP schemas sit in the prompt-cached
prefix, so a wide surface is nearly free. That is still true, and it is still not the
reason these went. A tool an agent never calls is not a cost problem, it is a signal that
the capability is unreachable, already covered, or imaginary. 3 of them were called 0
times in 20 days of daily real use. Keeping them means maintaining, testing and
documenting behaviour that nothing exercises, which is how a surface rots without anyone
noticing.

What did not go, and why the same argument does not reach it: `handle_dialog` and
`upload_file` also see little use, but neither has an `evaluate` fallback, so removing
them removes the capability outright. Low usage justifies removal only when the capability
survives elsewhere. `close_page` sees 0 calls, and that is the problem rather than the
justification: agents open tabs and never close them, so the fix is to teach the practice
in the server instructions. `list_sessions` is a diagnostic for the human, not a workflow
tool for the agent, so agent call counts are the wrong measure for it.

Each removal carries the condition that would reopen it:

- `drag`: a blocked-site report showing a pointer-drag control with no keyboard path, a
  slider captcha being the obvious case. That sits squarely on the anti-detection thesis
  and would justify a real-mouse drag rather than a synthetic one.
- `go_forward`: only if back and forward ever become real Firefox session history. Today
  the stack is a per-tab list fed only by `navigate`, so forward could only replay a URL
  the agent supplied itself and still holds.
- `performance_summary`: only if page-speed auditing becomes a stated use case.
- `hover`: real failures on hover-only menus with no click fallback. 1 call in 20 days
  says they are rare in practice, and this is the least obvious of the 5.
- `type_text`: a field `fill` cannot write, meaning one that reacts only to per-key events
  and that a snapshot cannot address by uid. `fill` already focuses and types key by key,
  so the gap is narrow.

Exact signatures, return formats and substitutes are in the
[changelog](CHANGELOG.md), written so any of them can be restored from that entry alone.

## Humanized cursor off by default

Camoufox can move the mouse along a human-looking path (`humanize`). It is real
anti-detection value and it is disabled by default, because it intermittently wedges the
browser and there is no recovery: synthesised mouse events are serialised on a
process-global promise chain, and each dispatch waits for an acknowledgement from the
renderer. A missed acknowledgement never arrives, the chain never advances, and every
later input event in that process queues behind it forever.

The timeline matters, because it is easy to assume this is already fixed upstream. The 2
known triggers were fixed upstream in July 2026, and our browser build carried both fixes
when we measured the freeze on 2026-08-03. So the freeze we see is the residual class, not
the triggers: upstream says as much, and tracks it as still open with no timeline. It has
also happened in production rather than only under test, where 1 `click_at` ran for
2,004,856 ms, which is 33 minutes.

Set `CAMOUFOX_HUMANIZE` to a duration in seconds if you want it and can tolerate a hang
with no timeout. When it is set, the value reaches Camoufox as a float on purpose:
Camoufox tests `isinstance(humanize, (int, float))`, and because Python's `bool` subclasses
`int`, a bare `True` would send `humanize:maxTime = true`, which Firefox rejects as "not a
double". Upstream still has no normalisation for that, so the guarantee stays ours.

## Camoufox and Playwright are pinned together, and so is the browser build

`pyproject.toml` bounds both (`camoufox[geoip]>=0.5.4,<0.6`, `playwright>=1.60,<1.61`) and
that is deliberate. An unbounded transitive Playwright once drifted ahead of the installed
Camoufox binary's Juggler schema and started emitting a `Browser.setDefaultViewport`
payload the binary rejected. Every launch failed until the binary auto-updated. It was a
cross-version protocol mismatch, not a bug in the launch code. The upper bound now agrees
with what Camoufox itself declares rather than being a private guess.

The pip version does not decide which browser runs. The launcher resolves the newest
upstream build inside a release-ordinal range, which is how this project silently moved
from one Firefox major to another under a launcher from the previous year, without any
change on our side. `CAMOUFOX_BROWSER_VERSION` pins the build we actually test against.
Leave it unset only if you want that drift.

When bumping any of the 3, bump them consciously and re-run the full E2E suite.

## fastmcp stays below 4 until the suite is green on 4

`pyproject.toml` declares `fastmcp>=3.4.4,<4`, and the upper bound is deliberate. `uv.lock`
binds only `uv sync`; `uv tool install`, which is how users install, ignores it and resolves
the pyproject constraints fresh. With fastmcp unbounded above, that resolution shipped
fastmcp 4.0.3 / mcp 2.2.0 to users on 2026-08-31 while the lock, and so every test run,
sat on fastmcp 3.4.4 / mcp 1.26.0: an untested major reached users before it reached CI.
The bound makes the installed stack the tested one. It was introduced in the 0.4.1 commits,
but neither 0.4.0 nor 0.4.1 reached PyPI (both release runs failed the metadata check), so
0.4.2 is the first release that ships it, on fastmcp 3.4.4 / mcp 1.26.0, unchanged.

The full suite measured on fastmcp 4.0.3 / mcp 2.2.0 fails 6 tests, none environmental:

- `tests/test_daemon.py`, `tests/test_daemon_advert.py`, `tests/test_daemon_recovery.py`
  and `tests/test_daemon_socket_path.py` fail at collection: mcp 2.2.0 depends on `httpx2`
  (module `httpx2`), so `httpx` is no longer installed transitively, and
  `daemon/spawn.py`, `daemon/endpoint_loopback.py`, `daemon/recovery.py` and
  `daemon/endpoint.py` import it directly. That import was never declared in
  `pyproject.toml`; the opt-in daemon only worked because httpx 0.28.1 arrived through
  fastmcp 3.
- `tests/test_tool_payload.py::test_server_instructions_are_served` and
  `tests/test_tool_payload.py::test_the_observe_bullet_states_the_cost_not_only_the_win`
  assert on `client.initialize_result`, which the fastmcp 4 `Client` leaves `None` in its
  default `auto` mode. The wire initialize result still carries the 2,629-character
  instructions, and `client.instructions` exposes them, so the doctrine is served: the
  test reads a field the new client no longer populates.

**Follow-up, "fastmcp 4 migration"**: move the daemon's HTTP client to what mcp 2 ships
(or declare the client it needs, as pydantic is declared, never rely on a transitive
again), read instructions through the fastmcp 4 client API in the 2 payload tests, run the
whole suite on the new stack on 3.12 and 3.13, then raise the bound to `<5` and re-lock in
the same change. Until that lands, `make test-latest` proves the newest 3.x users get, and
`fastmcp<4` is not a pin to relax casually.

## stdio only

The client-facing transport is stdio. The server is spawned as a subprocess by an MCP
client and is never exposed on a network port.

The optional shared daemon does speak HTTP internally, but over a private Unix domain
socket on POSIX (mode `0600`, in a `0700` directory) or a token-guarded `127.0.0.1`
loopback socket on Windows. Neither is a routable service. A browser holding your
authenticated sessions is not something to put behind an HTTP listener.

## Profiles stay on local disk

No S3, no cloud sync, no profile sharing. A profile directory contains live session
cookies for every site you signed into with it. Syncing that anywhere is a security
decision the user should make with their own tools, not something this project does
by default.

## No session TTL

Sessions close when you call `close_session`, or when the process exits. Nothing
evicts them on a timer. An agent that comes back to a tab twenty minutes later should
find it where it left it.

The daemon has its own idle TTL, but it only fires at zero active sessions and zero
in-flight requests, so it never kills a live browser to hit a timeout.

## No file chooser interception

A site's "Add media" button calls `input.click()` on a hidden file input, and the browser
answers with its native file dialog: a real window on a visible desktop, a silent no-op in
headless. Playwright can intercept it, and only when a client subscribes to `filechooser`
does the driver ask Juggler to. Subscribing at tab creation would make that click inert
on every OS, which is what an agent that clicked the button anyway would want.

We do not subscribe, because the interception writes to the page. To carry the event the
driver builds an `ElementHandle` for the input (`_onFileChooserOpened`, coreBundle.js:43499
at playwright 1.60), and that constructor instantiates the driver's injected script in the
page's main world (:16046 -> :16049). Measured with the suite's probes on the composer
page: 1 `MutationObserver` and the 13-listener branded set on `window`, the same footprint
`tests/test_driver_footprint.py` pins for a DOM node logged to the console, and nothing at
all without the listener. Our own handler is not involved; the leak is in the driver
process, and no client-side switch avoids it. The line numbers are bound to the pinned
driver and are refreshed on the next deliberate bump.

So the answer to that dialog is guidance and a route, not a listener: the UPLOADING block
of the server instructions says never to click the button, and `upload_file` takes
`selector="input[type=file]"`, which binds a hidden input without the visibility gate.
The recovery path an agent takes after clicking anyway, the same tab still answering and
the selector route attaching, is proved by `tests/test_upload.py`; the absence of the
subscription is read off the source by `tests/test_driver_footprint.py`. Should the driver
ever intercept the dialog without a handle, this decision is up for revisiting.

## uBlock Origin stays on

Camoufox adds its own addons to every browser it launches, uBlock Origin among them, and
0.3.4 added `CAMOUFOX_BUNDLED_ADDONS=false` for anyone who wants a browser without them.
The default stays `true`.

It is a real trade, so here is the losing side stated fairly. uBO writes to the page: it
inserts a `<script>` into `<head>` and removes it again, which is DOM activity we neither
version nor control. A blocked request is also an observable difference, and a site
expecting its own analytics call sees it missing. We do not own its filter lists or its
update cadence, yet its behaviour lands inside our anti-detection claim.

We keep it anyway. It is what Camoufox ships and what its fingerprinting work was tuned
against, so removing it makes this project the odd one out rather than the safe one. It
cuts a large amount of ad and tracker traffic out of `list_network_requests`, which is
noise an agent pays for in tokens on every listing. And blocking is now so common that its
absence is at least as remarkable as its presence.

Two levers exist for the case where a specific site disagrees, and neither weakens the
default. `CAMOUFOX_BUNDLED_ADDONS=false` is server-wide and removes only the bundled addons;
the marker test uses it, because measuring our own footprint requires a page with nobody else
writing to it: uBO's 3 mutation records were credited to us and blocked a release before that
was understood. `navigate`'s `block_trackers=false` is the per-session one, and it goes
further than uBO: alongside the same exclusion it turns off Firefox's own tracking
protection and its tracker-cookie behaviour, so a tracker keeps the cross-site identity
that removing uBO alone would not give it back. The two are unioned, never
in competition.

Three things that widening does not need, so nobody re-adds them. SafeBrowsing: Camoufox's own
`camoufox.cfg` already disables all 5 `browser.safebrowsing.*.enabled` toggles it carries —
`blockedURIs`, `downloads`, `passwords`, `malware`, `phishing` — and blanks a 6th key,
`browser.safebrowsing.provider.mozilla.updateURL`, on every launch, so a
`block_trackers=false` session is neither more nor less exposed there than a default one, and
we ship no pref for it. `browser.contentblocking.category`: Juggler delivers preferences after
`browser-first-window-ready`, so the category machinery cannot clear ours — measured, on a
profile already reading `standard` — and the key would only be needed if pref delivery ever
moved back into a pre-launch `user.js`. And a way back: there is none per profile, because
those prefs land on the user branch and survive into `prefs.js`, so `block_trackers=false`
means a dedicated profile name rather than a flag you flip off later.
