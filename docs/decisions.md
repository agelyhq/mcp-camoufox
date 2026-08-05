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
