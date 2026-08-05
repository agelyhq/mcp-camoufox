# 📝 Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `list_network_requests` and `list_console_messages` no longer go blank on a page that
  holds an iframe. Both monitors rotated their buffers on `framenavigated`, which fires
  for every frame, so an ad, a captcha or any embed navigating after load moved the
  document's own entries out of the default listing ("No network requests captured." on a
  page that had just loaded) and left every in-flight request reading `pending` forever.
  Only the tab's main frame rotates them now.
- A browser that fails to open its first tab is stopped instead of being left running.
  The failure used to escape between the launch and the bookkeeping, so the Camoufox
  process and its driver stayed alive holding the profile directory, while the server
  released the lock and reported an error.
- `close_session` and process shutdown are bounded at every step. Closing a tab, a
  context or the driver had no deadline, and Firefox can stop answering Juggler while
  its process stays alive, so one wedged tab could hang the exit forever.
- An addon download now has a timeout. An addon host that accepted the connection and
  then said nothing blocked session creation for the whole process, and a download cut
  short no longer leaves a truncated archive in the cache for every later run to trust.
- Answering a dialog with a word other than `accept` or `dismiss` no longer dismisses it
  anyway; the error is now `NoPendingDialogError` rather than a bare `RuntimeError`.
- A `viewport_width` supplied without a `viewport_height` (or the reverse) is refused
  instead of being silently dropped.

### Changed

- Downloaded addon archives are cached under `<data_dir>/addons/` (`CAMOUFOX_DATA_DIR`)
  instead of `~/.cache/camoufox-mcp/addons`, like every other path the server owns. They
  are re-downloaded once.
- One cold browser launch no longer blocks the first call of every other profile: launch
  locking is per profile, which matters most in daemon mode.

## [0.3.0] - 2026-08-05

Identity that leaves nothing in the page, 2 new tools, and 37% fewer tokens at session
start.

### Added

- `find(profile, role=None, name=None, text=None, label=None, placeholder=None,
  test_id=None, css=None, exact=False, limit=5)` locates elements without paying for a
  full snapshot, and mints real uids that `click`, `fill` and `get_element` accept with no
  snapshot in between. It is read-only and never activates anything. When a query matches
  nothing it reports what it did see, so a typo becomes a fix rather than a blind retry:
  asking for a heading named "Skillz" answers that 2 headings exist and names them.
- `get_element(profile, prop="text", uid=None, selector=None, limit=1, max_chars=4000,
  name=None)` reads one property of one element without writing JavaScript. `prop` is one
  of `text`, `value`, `attribute`, `state`, `box`, `style`, `count`; `attribute` and
  `style` take a `name`. A value never comes back blank: a property that does not apply
  raises and names the tag, a real but empty value reads `(empty)`, an absent attribute
  reads `(not set)`, and a selector that matched several elements says so instead of
  hiding it.
- `evaluate` accepts `uids`, passing resolved elements straight into the script as
  arguments, so a script no longer has to re-find by selector an element the agent already
  holds. `querySelector` appeared in 60% of measured scripts largely for that reason.
- `evaluate` gained `max_chars` and `max_items`. It was the only tool returning page
  content with no cap at all: 1 real call returned 353,120 characters, and 3 calls out of
  2,339 accounted for 45% of all its output. An array is cut at the element boundary so
  the result still parses, and every truncation now states the total and names the
  parameter to raise.
- `click`, `click_at`, `fill`, `go_back` and `reload` append a `[page]` line when the page
  actually moved. 91 measured `evaluate` calls existed only to read the current URL. The
  line is one-directional evidence: its presence means the tab moved, its absence proves
  nothing, since a navigation can commit after the confirmation window.

### Changed

- **Element identity no longer touches the page.** `snapshot` used to stamp
  `data-mcp-uid="eN"` on every interactive element and leave it there until the next
  capture, which is an unambiguous automation marker for a project whose whole argument is
  that pages cannot tell. Identity now lives in a table inside the tab's own heap, held
  from Python through a single handle. Measured on a live browser, across every path that
  consumes a uid: 0 attributes written, 0 mutations observed, 0 listeners added, 0
  observers constructed, 0 globals or symbols added.
- **A uid names 1 element, in 1 tab, in 1 document.** The counter used to restart at 0 on
  every capture, so `e5` in 2 consecutive snapshots could be 2 different elements and an
  agent acting on a recycled uid got a success report for the wrong thing. An element still
  present keeps the uid it already had, whatever moved around it. Carrying a uid to another
  tab or across a navigation now raises the stale-uid error instead of resolving to
  something else: each document gets its own numbering block, so a foreign uid is simply
  absent rather than valid-but-wrong. The visible price is that uid numbers no longer follow
  document order and grow wider after the first document.
- **Clicking by uid verifies its target.** It used to resolve a centre point and click the
  coordinates blind, so a cookie banner absorbed the click and the tool still reported
  success. A covered element now raises an error naming what is in the way.
- **Actions no longer go through Playwright selectors, locators or element handles.** Every
  one of those dispatches an automation event on the target before acting, and creating any
  element handle installs 13 listeners plus an observer in the page's own realm. Measured
  before the change: a `fill` fired 2 such events, a selector-based `click` fired 1.
  `wait_for` and `screenshot` were leaking the same way and were rewritten too.
- **Selectors are ours now:** plain CSS, plus `:has-text("...")` and `text=...`, which
  together covered every non-CSS selector in the measurement window. A list is resolved per
  comma branch and unioned in document order. Any other special syntax raises an error
  naming what is supported rather than silently matching nothing.
- `snapshot` defaults to `interactive_only=True`, and computes a real accessible name.
  `<button><span>Send</span></button>` used to render with no name at all, which is the
  most common shape on the modern web.
- `wait_for(condition="predicate")` reports the last value the expression returned when it
  times out. It failed 23.8% of 189 real calls and always burned the full timeout with
  nothing to diagnose.
- One truncation note across the product, stating the total and naming the parameter to
  raise. The old `[truncated N chars]` said something was lost but not how much or what to
  do about it.
- **BREAKING: the distribution and both console scripts are renamed to `mcp-camoufox`.**
  `camoufox-mcp` was published on PyPI by an unrelated author in January 2026, so the name
  this project used up to 0.2.0 is not available and the rename is forced rather than
  cosmetic. The commands are now `mcp-camoufox` and `mcp-camoufox-daemon`, with no alias:
  an existing MCP client config naming `camoufox-mcp` stops working and needs 1 line
  changed. The on-disk paths deliberately did NOT move: the data directory is still
  `camoufox-mcp`, so every existing profile and its logins keep working. That mismatch
  between the package name and the directory name is intentional.
- **The tool surface costs 37% fewer tokens at session start.** Doctrine that was repeated
  in 27 docstrings, uid lifetime, the observe modes, the selector syntax, profile isolation
  and the error contract, is now stated once in the server instructions. Measured on the
  serialised `tools/list` payload: 38,843 characters before this release, 22,263 after,
  about 10,800 tokens down to about 6,200. Tool descriptions alone fell 79%. Nothing
  documented was dropped: what left a docstring reappears in a parameter description or in
  the instructions. `tests/payload_baseline.json` records the number and a test fails when
  it grows past the margin, because that number had never been measured and was how it got
  to 38,843 unnoticed.
- The server instructions now teach the 5 behaviours the usage data showed were missing:
  1 profile per conversation named for the work, closing tabs (`close_page` had 0 calls
  against 7 `new_page`), `observe` to collapse a round trip (ignored on 70% of actions),
  reaching for a tool before `evaluate` (31.6% of all calls), and preferring a snapshot to
  a screenshot (images outnumbered snapshots 2.3 to 1, for 751,062 estimated image tokens).
- Camoufox moves to 0.5.4 and Playwright to 1.60. The previous bound was believed to hold
  the browser on Firefox 135; it never did, because the launcher resolves the newest
  browser release matching a release-ordinal range rather than a Firefox version. What the
  upgrade actually buys is the Python half: the guard against the `new_page()` deadlock
  under a spoofed window, which is exactly how this server launches, plus speech-voice
  spoofing, architecture and screen-geometry fixes, media-device defaults and fingerprint
  presets. Playwright 1.61 is excluded deliberately: it sends a viewport field the bundled
  protocol schema does not know, which is the failure that first put these 2 pins in
  lockstep.
- The browser build is pinned with `CAMOUFOX_BROWSER_VERSION` instead of following
  whatever the upstream project published last. A launcher silently moving from one
  Firefox major to another underneath a running install is the same class of incident the
  Playwright bound exists to prevent.
- Each browser launch gets its own environment, so `CAMOUFOX_HEADLESS=virtual` no longer
  repoints the display for every other session in the process. A visible session created
  after a virtual one used to inherit the throwaway 1x1 display.
- The daemon control socket moved from the data directory to the runtime directory, with a
  digest of the data directory in its name. A Unix socket path is capped near 108 bytes, so
  a long data directory made the daemon unbindable with an opaque error; the digest keeps 2
  configurations from meeting on 1 channel now that the path no longer contains the data
  directory. A running daemon records the address it bound so discovery still works when 2
  processes disagree about the runtime directory. The length is validated at bind time and
  raises an error naming the limit. Windows is unaffected.
- The daemon proxy re-checks health on a request failure and respawns once, with a bounded
  retry, so a daemon that dies mid-conversation costs 1 slow call instead of every call
  that follows. Live sessions are gone either way, and the error says so.
- An advert is never removed without proving it belongs to the daemon being shut down. A
  session landing between the health probe and the shutdown call used to leave a live
  daemon serving with no reachable control channel and its browsers orphaned.

### Removed

5 tools retired after the measurement window closed on 8,795 real tool calls across 158
profiles and 20 days. Each entry below carries the signature, the behaviour and the
substitute, so any of them can be restored from this changelog alone without reading git
history. The reasoning, and the condition that would reopen each one, is in
[decisions.md](decisions.md).

- `drag(profile, from_uid, to_uid)`, 0 calls. Resolved both centres and drove
  `mouse.move` / `mouse.down` / `mouse.move` / `mouse.up`, returning
  `Dragged <tag> to <tag>`. Substitute: `evaluate` dispatching the drag event sequence
  the page actually listens for. A synthetic pointer drag rarely satisfies a real
  drag-and-drop implementation anyway, which is part of why nobody reached for it.
- `go_forward(profile, timeout=30000)`, 0 calls. Re-navigated to the next URL on the
  per-tab history stack, returning `Went forward to <url>` or an error when there was
  nothing ahead. Substitute: `navigate` with the URL. The stack was fed only by
  `navigate`, so forward could only ever replay a URL the agent had itself supplied.
  `go_back` stays, at 15 calls, and is the natural way out of a wrong click.
- `hover(profile, uid)`, 1 call. Resolved the element centre and issued `mouse.move`,
  returning `Hovered <tag> at (x, y)`. Substitute: `evaluate` dispatching a `mouseover`
  event, or `click` where the menu also opens on click. This is the one whose removal is
  least obvious, since a hover-only menu has no clean substitute.
- `performance_summary(profile)`, 0 calls. Read W3C Navigation and Resource Timing for
  the active tab and formatted a report: DNS, TCP, TLS, TTFB, DOM content loaded, load
  event, plus the 10 largest resources by transfer size. Substitute: `evaluate` over
  `performance.getEntriesByType("navigation")` and `("resource")`. Only the formatting
  was ours.
- `type_text(profile, text, delay=0, press_enter=False)`, 7 calls. Typed into whatever
  had focus using `keyboard.type`, optionally pressing Enter, returning
  `Typed <n> chars`. Substitute: `fill`, which targets explicitly and is far more used at
  103 calls, combined with `press_key` at 903. Typing into an implicit target depends on
  focus state the agent cannot see, which is the less reliable pattern.

`Page.forward_url()` was deleted with `go_forward`, its only caller.

### Fixed

- A uid carried to another tab, or across a navigation, used to resolve to a different
  element and report success. Each document now numbers from its own block, so a foreign
  uid is absent rather than valid-but-wrong and raises the stale-uid error. This was the
  same silent-wrong-element failure the release set out to remove, surviving in another
  dimension, and it was found by an independent revalidation rather than by the suite.
- A daemon killed while a request was in flight wedged the conversation with no timeout to
  rescue it, because nothing raises when a response simply never arrives. The proxy now
  watches outstanding requests and cancels only on proof of death, confirmed twice. A
  timeout is deliberately not proof: a cold browser launch can block the daemon longer than
  a probe, and cancelling a healthy call is worse than waiting for a slow one.
- Accessible names no longer fold a control's own data into its name (a label wrapping a
  select rendered as the label text followed by every option), and an icon control now
  takes its name from the image's alternative text instead of having none.
- `get_element(prop="box")` scrolls its target into view before measuring, so the
  coordinates it hands to `click_at` reach the element instead of pointing below the fold.
- `get_element` with a limit above 1 no longer discards every good match because 1 match
  does not support the property.
- `find(exact=True)` compares against the real accessible name instead of re-parsing its
  own rendered output, which returned the wrong element for a name ending in parentheses.
- An observed action that navigates no longer returns 2 contradictory page lines with a
  uid tree belonging to the document that just died.
- A pinned browser build is re-asserted as active on startup instead of only during the
  24 hour update check, so a pinned but inactive install can no longer spoof a Firefox
  version that is not the one running.

- `TypeError: function takes exactly 5 arguments (1 given)`, the most frequent error in
  real usage at 133 occurrences across 9 tools. The network monitor read
  `request.post_data`, which Playwright implements as a strict utf-8 decode of the raw
  body, so any page posting a binary body raised `UnicodeDecodeError` inside Playwright's
  event dispatch. Playwright stashes such an error on the connection and re-raises it on
  the next API call, where it rebuilds the exception with a single argument, and
  `UnicodeDecodeError` needs 5. The result landed on an unrelated tool, before any I/O,
  with no traceback anywhere. The body is now read from the raw buffer and decoded
  defensively, and a binary body is reported as its byte count.
- Unexpected exception types now leave a full traceback in the server log while the tool
  result stays exactly 1 line. This covers the tool wrapper and the observation path, the
  latter of which had been hiding a failure behind an `ok: true` record.
- Browser launch failures under `CAMOUFOX_HEADLESS=virtual`. Camoufox 0.4.11 guessed an
  Xvfb display number in userspace, started the server and returned without waiting for
  it to be ready, leaving the lock file behind on teardown. 0.5.4 lets Xvfb pick the
  display atomically and report back, with a deadline and a hard kill. Combined with the
  per-launch environment fix below, this closes the 21 launch failures recorded over 6
  separate days.

### Security

- Profile names are validated before they reach a disk path. A name was previously taken
  verbatim, so `../../pwned` wrote the profile directory and the telemetry log 2 levels
  above the data root, an absolute name wrote wherever it pointed, and a name of `..`
  resolved the profile directory to the data root itself, which was then handed to Firefox
  as a profile directory containing every other profile. A name must now match
  `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, checked on both paths that consume it, because the
  tool wrapper logs even a call the session layer has just rejected. Nothing is silently
  sanitised: an agent that asks for a bad name gets a one-line error saying what is
  allowed, never a different profile than the one it asked for.

## [0.2.0] - 2026-08-04

Windows support, and a documentation set worth reading.

### Added

- Windows support for both the stdio server and the optional daemon. The daemon
  control channel is now platform-abstracted: a Unix domain socket on POSIX, and a
  `127.0.0.1` loopback socket guarded by a per-daemon bearer token on Windows.
- `snapshot` surfaces a form control's associated `<label for>` text as `label=<text>`.
  Without it, a `<select>` or an input with no `name` and no `placeholder` could not be
  targeted by its visible name, which is how most real forms are written.
- Documentation in `docs/`, one page per task: getting started, profiles, anti-bot,
  isolation, tools, configuration, daemon, telemetry, architecture and decisions, plus
  contributing guidelines and this changelog. Issue templates for bug reports and for
  sites that still block the browser.
- `CAMOUFOX_HUMANIZE`, which takes a duration in seconds, enables Camoufox's humanised
  mouse movement.
- Every test is bounded by `pytest-timeout`, so a browser dying mid-call fails the run
  instead of hanging it forever.

### Changed

- The humanised cursor is now opt-in and off by default. With it enabled, Firefox
  intermittently stops answering the Juggler protocol part-way through a mouse event
  while the process stays alive, so the pending click never returns. Every E2E run with
  it on froze at a random test; every run without it passed the whole suite.
- `CAMOUFOX_HEADLESS=virtual` is rejected at launch on Windows and macOS. Xvfb does not
  exist there, so use `true` instead.

### Fixed

- `fill` on a `<select>` now picks the matching option instead of typing into it. It
  matches on option value, then on visible label, then case-insensitively, and lists the
  available options when nothing matches. Typing relied on Firefox type-ahead matching,
  which silently selected the wrong option whenever the value was not a unique prefix.
- The daemon proxy is imported lazily, so the server starts on Windows.
- The daemon bearer token is compared as bytes.
- `humanize` reaches Camoufox as a float. Python's `bool` subclasses `int`, so passing
  `True` sent `humanize:maxTime = true`, which Firefox rejects as "not a double".

## [0.1.1] - 2026-08-03

### Added

- E2E coverage for several profiles driven simultaneously from one process.

## [0.1.0] - 2026-07-17

First usable release: a FastMCP stdio server exposing 30 browser-automation tools
backed by Camoufox, with per-profile session isolation.

### Added

- 30 tools covering navigation, tabs, inspection, interaction, scripting, network,
  console and performance. Every tool takes a mandatory `profile` argument.
- Per-profile session manager: a session is created lazily on first use, backed by a
  persistent on-disk Camoufox context and a cross-process lock, so 2 conversations
  never share a browser by accident.
- UID snapshot system: `snapshot` walks the visible DOM with ARIA heuristics and stamps `eN` uids on
  interactive elements, which the interaction tools then target.
- Optional shared daemon (`CAMOUFOX_DAEMON=true`) so several conversations can share
  one set of browsers through a thin stdio proxy. Off by default, and the default path
  is unchanged when it is off.
- Per-profile JSONL telemetry with measurable records: result sizes, image token
  estimates for screenshots, and `evaluate` intent buckets.
- `observe` on `click`, `click_at`, `fill` and `navigate`, which appends a post-action
  snapshot or text dump to the result and saves a round trip.
- `screenshot` downscaling through `max_width`, which returns the coordinate multiplier
  alongside the image.
- Env-driven configuration: headless mode, proxy with GeoIP, fingerprint OS, viewport,
  locale, data directory, addons, auto-update.
- Throttled, non-blocking, fail-open auto-update of the browser binary and GeoIP
  database. Only a cold install blocks startup.
- Full E2E suite against a real Camoufox browser and a local Flask server. Nothing
  browser-side is mocked and no internet access is needed.

### Changed

- `scroll` moves the viewport with `window.scrollBy` instead of `mouse.wheel`, which is
  inert on headless Firefox.
- Tool errors render as a single line. The Playwright call log tail is stripped and
  newlines are folded.
- `camoufox` and `playwright` are version-bounded together. An unbounded transitive
  Playwright once drifted ahead of the installed browser binary's protocol schema and
  every launch failed.

### Fixed

- Profile directories are created owner-only.

### Removed

- The S3 profile sync stack. Profiles are local-disk only.

[Unreleased]: https://github.com/agelyhq/mcp-camoufox/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/agelyhq/mcp-camoufox/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/agelyhq/mcp-camoufox/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/agelyhq/mcp-camoufox/releases/tag/v0.1.1
[0.1.0]: https://github.com/agelyhq/mcp-camoufox/tree/1798b33940fd8d0c51c3491db2d98f6d5a79b8a2
