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

These exist in `chrome-devtools-mcp` and will never exist here, because they are
V8 or CDP features with no Firefox equivalent:

- Heap snapshots (`take_heapsnapshot`): V8-specific memory profiling.
- Chrome performance tracing (`performance_start_trace`, `performance_stop_trace`,
  `performance_analyze_insight`): the CDP trace format does not exist on Firefox.
  `performance_summary` covers the same ground through the standard W3C Navigation
  and Resource Timing APIs.
- Lighthouse audits: built on Chrome's CDP auditing pipeline.
- Screencast, CPU throttling, device emulation presets: CDP session features with no
  Playwright/Firefox equivalent worth faking.

Emulating these badly would be worse than not having them.

## No `resize_page` or `emulate`

These were the only non-CDP gaps against `chrome-devtools-mcp` v1.6.0, and they will
not be implemented as specified.

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

## No tool removal, for now

Roughly half the tools see 0 usage in telemetry, which normally argues for removing
them. It does not here:

- MCP tool schemas sit in the prompt-cached prefix, so after the first turn they cost
  about a tenth of their nominal price, and recent Claude Code versions defer schemas
  through tool search anyway. The token argument for a smaller surface does not hold.
- `handle_dialog` and `upload_file` have no `evaluate` fallback. If they go, the
  capability goes.
- `performance_summary` is W3C Navigation Timing, which is Firefox-native and in scope.

Enriched telemetry (result sizes, image token estimates, `evaluate` intent buckets)
shipped in July 2026, so the surface gets re-reviewed once there is enough real usage
data to justify a removal.

## Humanized cursor off by default

Camoufox can move the mouse along a human-looking path (`humanize`). It is real
anti-detection value and it is disabled by default, because it intermittently wedges
the browser: Firefox stops answering the Juggler protocol part-way through a
`Page.dispatchMouseEvent` while the process stays alive, so the pending click or hover
never returns and the caller hangs forever.

This was measured, not guessed. Every E2E run with `humanize` on froze at a random
test. Every run without it passed the whole suite.

Set `CAMOUFOX_HUMANIZE` to a duration in seconds if you need it and can tolerate that
failure mode. When it is set, the value reaches Camoufox as a float on purpose:
Camoufox tests `isinstance(humanize, (int, float))`, and because Python's `bool`
subclasses `int`, a bare `True` would send `humanize:maxTime = true`, which Firefox
rejects as "not a double".

## Camoufox and Playwright are pinned together

`pyproject.toml` bounds both (`camoufox<0.5`, `playwright>=1.58,<1.59`) and that is
deliberate. An unbounded transitive Playwright once drifted ahead of the installed
Camoufox binary's Juggler schema and started emitting a `Browser.setDefaultViewport`
payload the binary rejected. Every launch failed until the binary auto-updated. It was
a cross-version protocol mismatch, not a bug in the launch code.

When bumping either one, bump both consciously and re-run the full E2E suite.

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
