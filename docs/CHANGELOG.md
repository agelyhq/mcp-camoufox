# 📝 Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Documentation reorganised: the README is now an introduction and an install guide,
  and the full reference moved to `docs/`.

## [0.2.0] - 2026-08-03

Windows support.

### Added

- Windows support for both the stdio server and the optional daemon. The daemon
  control channel is now platform-abstracted: a Unix domain socket on POSIX, and a
  `127.0.0.1` loopback socket guarded by a per-daemon bearer token on Windows.
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

[Unreleased]: https://github.com/agelyhq/mcp-camoufox/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/agelyhq/mcp-camoufox/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/agelyhq/mcp-camoufox/releases/tag/v0.1.1
[0.1.0]: https://github.com/agelyhq/mcp-camoufox/tree/1798b33940fd8d0c51c3491db2d98f6d5a79b8a2
