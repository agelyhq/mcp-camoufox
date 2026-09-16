# 📝 Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.3] - 2026-09-16

`upload_file` attaches a file from a Windows desktop again. The report was "cannot attach a
file from disk" on Claude Desktop; the diagnosis found 3 confirmed defects, none of them
Windows-specific in the code, that a visible-window Windows session trips over far more often
than a Linux one, plus 5 Windows edge cases the read path could not prove correct. All are
addressed but one, which is argued shut instead.

### Fixed

- **A hidden `<input type=file>` was unreachable.** Every uid mint runs the visibility gate,
  so a site's `display:none` or `opacity:0` file input (the LinkedIn shape, where the "Add
  media" button is a sibling of the input) never got a uid, `upload_file` took `uid` only,
  and the only uid the agent could obtain answered `no file input found`. `upload_file` now
  takes `uid` XOR `selector`, resolved through the same `tools/_target.py` rule as `click`
  and `fill`, and its selector arm binds the first match WITHOUT the visibility gate, so
  `selector="input[type=file]"` attaches to an input the site keeps hidden. `find`,
  `click` and `fill` keep the gate.
- **The path was taken literally.** No strip, quote removal, `~`/`%VAR%` expansion, `file:`
  conversion or absolute-path check existed, and `Path.is_file` swallowed ENOENT, ENOTDIR
  and the Win32 invalid-name errors alike, so Explorer's "Copy as path" (double quotes),
  `%USERPROFILE%\...`, `file:///C:/...`, `/mnt/c/...` and a bare relative name all collapsed
  into `'<path>' is not a readable file`. `dom/upload_path.py` now resolves, in order:
  surrounding whitespace, one pair of matching quotes, a `file:` URI, `%VAR%`/`$VAR`, `~`;
  then refuses a relative path naming the server's working directory (with a WSL hint on
  Windows for `/mnt/<letter>/`); `dom/upload_read.py` reports every `stat` refusal with its strerror, errno
  and winerror, the checked path when it differs from the typed one, and the length once
  it is at or past Win32's 260-character ceiling.
- **A read that failed after a passing `stat` was off-contract.** The bytes were read
  synchronously on the event loop with no `OSError` handling, so a OneDrive placeholder
  that OneDrive could not hydrate or a file another program holds exclusively rendered as
  `Error: PermissionError: [Errno 13] ...` (or `OSError: [Errno 22]`) with a traceback in
  the server log, and a slowly hydrating file froze every in-flight call. The read now runs
  on a daemon thread under `READ_TIMEOUT` (30 s), every `OSError` is a one-line
  `ValueError`, `EACCES` on Windows carries the open-in-another-program hint, and a
  placeholder (`FILE_ATTRIBUTE_OFFLINE` or `RECALL_ON_DATA_ACCESS`) is refused before the
  read that would block on it.
- **A trailing space in the path was silent on Windows.** Win32 strips trailing spaces and
  periods before NTFS, so the read succeeded while `path.name` kept the space, the MIME
  guess failed and the page received a `File` named `post.png ` of type
  `application/octet-stream`. The path is stripped first, `payload_name` applies the same
  Win32 rule lexically to the last component of a Windows path (never through `resolve()`,
  which would follow a symlink or junction and name its target; a `\\?\` path keeps its
  name as typed, since the prefix turns that normalisation off), and the confirmation line
  now states the name, type and size the page received (see Changed).
- **The MIME type came from the Windows registry.** `mimetypes` loads `HKCR\.ext` on
  Windows with nothing after it to re-assert the standard values, so a third-party
  installer's `image/pjpeg` or `image/x-png` reached the page verbatim. `dom/upload_mime.py`
  sniffs the magic bytes of PNG, JPEG, GIF, WebP and PDF first, then falls back to
  `mimetypes`, then `application/octet-stream`.
- **A path of 260 characters or more failed `stat` on Windows** with the generic line unless
  the `LongPathsEnabled` policy was on. Such a path is stat'ed and read in the `\\?\` form
  (`\\?\UNC\...` for a share), normalised with `ntpath.normpath` first because the prefix
  turns Win32 normalisation off; messages keep the typed spelling.

### Added

- `upload_file(profile, file_path, uid=None, selector=None)`: the `selector` parameter,
  with the `provide exactly one of uid or selector` rule `click` and `fill` already apply.
- An `UPLOADING` block in the server instructions and a rewritten `upload_file` docstring:
  never click a site's "Add media" / "Upload" button (it opens an OS dialog no tool can
  drive), call `upload_file` with `selector="input[type=file]"` or the label's uid,
  `file_path` is an absolute native path on the machine running the server, and a file
  attached to the chat has no disk path. `tests/payload_baseline.json` is re-baselined
  for it (`tools/list` 22,792 → 23,346 bytes, instructions 2,629 → 3,115).
- `tests/templates/composer.html` (`/composer`), a LinkedIn-shaped page: `display:none`
  and `opacity:0` sibling inputs, a form-wrapped one, buttons calling `input.click()`.
  `tests/test_upload_path.py` drives every path shape with a POSIX equivalent through the
  tool, `tests/test_upload_read.py` every disk refusal after the path resolved, and
  `tests/test_upload_win32.py` the Windows-only rules (`%USERPROFILE%`, `file:///C:/`, UNC,
  `C:foo` and `/mnt/c/` shapes, `\\?\` prefixing, the placeholder attribute,
  trailing-space stripping, the length note, the `EACCES` lock hint and the `winerror`
  rendering) as focused tests on `PureWindowsPath`: `resolve_upload_path` takes the path
  flavour as a public keyword and every Windows rule keys on it, never on `os.name`.
  `tests/upload_helpers.py` holds the Flask echo assertions the suites share.

### Changed

Every public string that moved, old → new, so the previous behaviour can be restored:

- Success line: `Uploaded {file_path} to {uid}` → `Uploaded {name} ({mime}, {size} bytes)
  to {uid}`, e.g. `Uploaded post.png (image/png, 48213 bytes) to e12`. The three values are
  what the page's `File` was built with, so a wrong name or type shows without a second
  call.
- `no file input found for uid '{uid}'` → `no file input found for uid '{uid}'; pass
  selector="input[type=file]" (a hidden input is accepted) or the uid of the input's
  <label>`.
- `'{file_path}' is not a readable file` splits into: `cannot read '{raw}': {strerror}
  (errno N[, winerror N])[ (checked '{path}')][; the path is L characters, past Win32's 260
  limit[, tried in the \\?\ form]]` for a missing file, a bad name or a denied directory;
  `'{raw}' is not a regular file[ (checked '{path}')]` for a directory, device or socket;
  `file_path must be an absolute path on this machine; got '{raw}'[ (expanded to '{text}')]
  (server working directory: {cwd})[; that is a WSL path: on Windows use C:\...]` for a
  relative path, which was previously tried against the working directory; the expansion
  is named when it changed the text, so a `$HOME/...` typed on Windows shows what it became.
- New strings with no predecessor: `cannot read '{raw}': {strerror} (errno N)[; the file may
  be open in another program: close it and retry]` (a read failing after `stat` passed,
  previously an off-contract `PermissionError`/`OSError` line); `'{raw}' is a OneDrive/cloud
  placeholder not downloaded on this machine; right-click it > 'Always keep on this device'
  and retry`; `Timeout: reading '{raw}' did not finish within 30s; a cloud-synced or network
  file may still be downloading`.
- `upload_file`'s telemetry record carries the `targets` list `click` and `fill` already
  write, since it now goes through the same target resolution.

### Decided

- **No `filechooser` interception**, although subscribing at tab creation would make a
  page-driven `input.click()` inert on every OS. It was implemented and measured with the
  suite's own probes: every delivered chooser event makes the driver build an
  `ElementHandle` for the input (`coreBundle.js:43499`, playwright 1.60), whose constructor
  instantiates the injected script in the page's main world, 1 `MutationObserver` plus the
  13-listener branded set on `window`, with nothing at all as the control. That is the
  footprint the "nothing is written to the page" invariant forbids, regardless of what the
  Python handler does, so the listener was removed before shipping. A click on "Add media"
  therefore still opens the native dialog on a visible window (a silent no-op in headless);
  the answer is the UPLOADING guidance and the selector route. Argued in
  `docs/decisions.md`, "No file chooser interception"; `tests/test_driver_footprint.py`
  fails if the subscription comes back.

### Validation on Windows

Only a Windows box proves the trailing-space stripping, the `\\?\` `stat` difference, the
placeholder and sharing-violation errnos and the actual `HKCR` MIME values. Install by git
ref (`uvx --from git+https://github.com/agelyhq/mcp-camoufox@v0.4.3 mcp-camoufox`, a new tag
is a new uv cache key), fully quit and relaunch Claude Desktop, confirm `selector` is listed
on `upload_file`, then upload a clean `C:\...` path, the same path as Explorer's "Copy as
path" quotes it, and a wrong name: expect `Uploaded post.png (image/png, N bytes) to eN`
twice and the `cannot read` line naming the checked path once.
`%LOCALAPPDATA%\camoufox-mcp\logs\<profile>.jsonl` holds the `args.file_path` and result
of every call.

## [0.4.2] - 2026-09-15

The release pipeline publishes again, and 3 findings from the 0.4.1 review are closed: the
fetch child can no longer hold a shutdown, the guard against a process-global stream swap
reads the syntax tree instead of the text, and the fetch child's docstring says what it
really does to the active build.

### Fixed

- **Neither 0.4.0 nor 0.4.1 ever reached PyPI.** `release.yml` checked the wheel's
  `Metadata-Version` as the literal text `2.4`; uv's build backend moved to 2.5 (uv 0.11),
  so the "Check the metadata" step refused both tags after `twine check --strict` had
  passed them, and PyPI stayed on 0.3.x. The version is now parsed and required to be
  2.4 or newer, which is what PEP 639's `License-Expression` actually needs.
- **A cancelled fetch could hang the shutdown.** asyncio resolves `Process.wait()` only
  once every pipe has reported EOF, and a `StreamReader` holding more than 128 KiB unread
  pauses its pipe, so a fetch child that printed a backlog after the parent stopped
  reading, then died, left `updater/child.py` awaiting an exit it could never observe:
  the terminate deadline expired, and the wait after `kill()` had no deadline at all.
  Terminating now drains stderr while it waits, and every step of the path is bounded
  (`TERMINATE_TIMEOUT_S`, then `KILL_TIMEOUT_S`, then a logged warning rather than a
  hang). `tests/test_fetch_child_teardown.py` drives the real child into that backlog
  through the environment it inherits and waits for the cancellation to complete.
- The fetch child's module docstring no longer claims it never activates a build:
  camoufox's `install_versioned` calls `set_active` on every install. Unpinned, that
  activation stands; pinned, the parent re-asserts the pin after every browser fetch.

### Changed

- `tests/test_no_stream_swaps.py` parses each source file with `ast` instead of matching
  5 substrings per line. It now catches `setattr(sys, ...)`, annotated, augmented and
  tuple targets, `with ... as sys.stdout`, `del`, writes into `vars(sys)` or
  `sys.__dict__`, `sys` imported under another name, and `contextlib.redirect_stdout` /
  `redirect_stderr` under any import alias; a docstring naming the swap is no longer a
  hit. Every spelling has a control proving it is detected, and every read a control
  proving it is not.

## [0.4.1] - 2026-09-15

A fresh install answers its first request again: the startup crash under fastmcp 4 / mcp 2
is fixed at its root, this process never touches the process-global streams any more, the
scenario that reproduces it runs in CI on the stack users actually install, and the
dependency policy stops letting an untested major reach users before it reaches the suite.

### Fixed

- **Startup crash on a fresh install under fastmcp>=4 / mcp>=2.** Every start died before
  `initialize` was answered, the host reporting "Connection closed" and the server log
  `AttributeError: '_io.StringIO' object has no attribute 'buffer'` from
  `mcp/server/stdio.py`. Root cause: the auto-updater ran camoufox's downloads under a
  process-global `sys.stdout`/`sys.stderr` redirect, entered from a worker thread, to keep
  the download's progress output off the wire; fastmcp 4 suspends between our lifespan's
  `yield` and the stdio transport's claim on fd 1, so a refresh that was due at that moment
  handed the transport a `StringIO` instead of the real stream. The stamp that throttles
  the refresh is written only by a completed one, so a crashed start re-armed the race on
  every restart. The fix: every fetch now runs in a child process
  (`python -m camoufox_mcp.updater.fetch <browser|geoip>`, spawned by `updater/child.py`
  with stdin and stdout on the null device and a bounded stderr tail as the failure
  message), the parent keeps the offline half (disk reads, activating the pin, the stamp)
  and terminates the child under a deadline at shutdown, and this process never assigns
  `sys.stdout` or `sys.stderr`: `tests/test_no_stream_swaps.py` reads the source to prove
  it, with `sessions/quiet.py` as the single exemption, safe because a session can only be
  created by a tool call, which can only arrive over a transport that already owns fd 1.
  `tests/test_stdio_startup.py` drives the real entry point over a real stdio transport
  with an empty data dir, the one scenario the in-process suite could not see; it is red on
  the pre-fix updater under fastmcp 4 and runs in `release.yml` through `make test-latest`,
  on the unlocked resolution `uv tool install` gives users, because the locked stack passes
  it with the bug present.
- A failed refresh no longer writes the 24h stamp, so a missing asset is retried at the
  next start instead of parked behind the throttle; the failure is one line in the server
  log, the child's own error rather than a traceback.

### Changed

- **Dependency policy: `fastmcp>=3.4.4,<4`.** `uv.lock` binds only `uv sync`; `uv tool
  install`, which is how users install, ignores it and resolves the pyproject bounds
  fresh. Unbounded above, that resolution shipped fastmcp 4.0.3 / mcp 2.2.0 to users on
  2026-08-31 while the lock, and so every test run, sat on fastmcp 3.4.4 / mcp 1.26.0: an
  untested major reached users before it reached CI. The upper bound makes the installed
  stack the tested one; the lock stays at fastmcp 3.4.4 / mcp 1.26.0, unchanged. The full
  suite measured on fastmcp 4 fails 6 tests, none environmental (the daemon's undeclared
  `httpx` import and 2 payload tests reading a client field the new client no longer
  populates); `docs/decisions.md` records them and the migration that has to land before
  the bound moves.
- `make test-latest` (new, also in `release.yml` after the full suite on both matrix
  legs) builds its own `.venv-latest` through `uv pip`, the one uv path that neither reads
  nor writes `uv.lock`, and runs `tests/test_stdio_startup.py` on the newest fastmcp/mcp
  the bounds allow with `--no-sync`, so uv cannot repair the environment back to the lock.
- `ServerConfig.child_env()` is the one way a subprocess (the daemon, the fetch child)
  learns its environment; `daemon/spawn.py` no longer reads `os.environ` itself, so
  `config.py` is the only reader again with no sanctioned exception.

## [0.4.0] - 2026-09-10

A way to let a page's own trackers through when they are the thing under test, telemetry that
names what a call addressed while refusing to write down the secret it carried, and a build
target that stopped stripping the dev dependencies out of the environment everything else runs
in.

### Added

- **A record now says WHAT was clicked or filled, not just which uid.** A uid names one
  element in one document, so `uid=e6600005` means nothing to anything reading the log
  afterwards, and a recipe generated from one could not name the button it was about. The
  `click`, `fill` and `fill_form` records carry a `targets` list, one entry per element the
  call ADDRESSED, in the order it addressed them and whether or not it was found: `uid`,
  the `selector` when that was the address, `tag`, `role`, `input_type`, `label` (the first
  of aria-label, the bound `<label>`, placeholder and form name that answers), the
  element's own `text`, and `secret: true` when a value must not be written down for it.
  An address is noted before any page work, so a stale uid and a selector that matched
  nothing each still get an entry — what was attempted is what a log is read for, and it is
  what the value redaction below is keyed on; `resolved` states in as many words whether
  the address found an element, rather than leaving a reader to infer it from which fields
  only the page can write. Every string among them is capped at the argument ceiling, since
  this object is flattened onto the line without passing through the argument truncation
  and the selector a caller sends and a custom element's `tag` are as long as whoever wrote
  them makes them; the names the page writes, the `role` attribute included, are capped at
  80 in the page instead, so a 65,000-character attribute never crosses the protocol at
  all — once per poll iteration is what it cost before. It costs no extra
  page call: the fields ride the `resolve` payload that every click and fill already
  measures, and the accessible-name computation that used to travel there — a walk
  collecting the whole subtree's text, per poll iteration, on the hottest path in the
  product — is still not run. One walk is kept and named: the text of the bound `<label>`,
  bounded by that label's own subtree and skipped for an element that has none, because it
  is the only visible name most form fields have. Declared per tool at registration, so the
  wrapper never learns a tool's name; carried from the body to the record through one
  scratch list per call, discarded with it.
- `block_trackers` on `navigate`, `false` to let tracker requests through. It defaults to
  `true`, so nothing changes unless you pass it: the default launch is byte-identical to a
  build that never knew the option, no `exclude_addons` and no `firefox_user_prefs`. It
  exists because a page's own analytics is sometimes the thing under test — Google
  Analytics, the Facebook pixel — and until now every profile blocked it with no way to ask
  otherwise. `false` turns off all 4 protections that can block or neuter such a request:
  Camoufox's bundled uBlock Origin, via `exclude_addons`; Firefox's Enhanced Tracking
  Protection, via `privacy.trackingprotection.enabled`, `.annotate_channels`,
  `.fingerprinting.enabled`, `.cryptomining.enabled`, `.socialtracking.enabled` and
  `.emailtracking.enabled`; cookie partitioning, via `network.cookie.cookieBehavior=0`,
  which is what leaves a tracker its identity across sites and which `camoufox.cfg` itself
  defaults to 4, not 0; and SafeBrowsing, which needs no preference of ours because `camoufox.cfg`
  already disables all 5 of its `.enabled` toggles on every launch — `blockedURIs`, `downloads`,
  `passwords`, `malware`, `phishing` — and blanks a 6th key, the Mozilla provider update URL.
  That browser therefore warns about
  no malicious page, on any value of the flag, and that price was accepted knowingly. It is
  a session-creation option like the others: it applies at a profile's first launch and is
  named in the ignored-options note afterwards. It is a tool parameter and nothing else, no
  environment variable: `CAMOUFOX_BUNDLED_ADDONS` keeps its own meaning, the server-wide
  "no extension at all" the marker probes need. The 2 levers are unioned — either one
  excludes uBlock Origin, neither can cancel the other, and only `block_trackers=false` also
  sends preferences. This project's own addon is untouched, since a cookie-banner dismisser
  blocks nothing. One consequence to know before using it: Playwright pushes those
  preferences onto the profile's user branch after startup, so Firefox writes them into
  `prefs.js` at shutdown and they stay off for every later launch that sends nothing. Only
  the uBlock Origin exclusion is per launch. One key was dropped from the set before it ever
  shipped and must not be re-added: `privacy.partition.network_state`, measured DEAD on the
  pinned Camoufox 152.0.4-beta.28 build. `camoufox.cfg` line 338 sets it, which is why it
  looked real, but nothing in the build reads it: `libxul` holds no NUL-terminated copy of
  the name (only the longer `.connection_with_proxy`), and with that cfg line commented out
  an int fed to the name through `user.js` survives into `prefs.js` exactly like two
  invented control names, where the real prefs in the same file — `.serviceWorkers`,
  `privacy.trackingprotection.enabled`, `network.cookie.cookieBehavior` — all reject the
  wrong type and vanish. Sending it therefore guaranteed nothing, and it carried a live
  hazard: an unregistered name takes the type of its first setter, so a bool from us against
  the cfg's `defaultPref` agrees only by luck, and the disagreeing case aborts browser
  startup outright (reproduced 3 times, 180 s launch timeout, no Juggler handshake). To
  re-check after a Firefox major bump: comment out that cfg line, feed the name an int,
  look for it in `prefs.js`. The cross-site-identity claim is unaffected — it was always
  carried by `network.cookie.cookieBehavior=0`, which is real and did bite.

### Changed

- **Tool arguments are kept up to 10,000 characters instead of 200.** Measured over the
  whole production history: the longest argument string ever recorded is 6,375 characters
  and the 99th percentile is 906, so the new ceiling keeps 100% of real arguments intact
  while still bounding a pathological one. The old 200 destroyed 60.4% of every `evaluate`
  script on disk, which is the single argument these logs are read for. Keeping the entire
  history untruncated measures 2.2 MB.
- **Results are kept up to 10,000 characters instead of 200.** Median 84, p95 3,085, p99
  7,743, max 353,120 (one snapshot): over 99% of results are now recorded whole and only
  the giant captures are clipped. The `...[N chars]` suffix and `result_chars` keep their
  meaning exactly. The 2 ceilings are 2 named constants rather than one shared number,
  because they answer different questions and will diverge.

### Fixed

- **`result_chars` was 1 character short per line of a multi-part result.** It summed the
  parts while the note it describes joins them with a newline, so a length that is read as
  "how much was clipped" disagreed with the string it was about. It is now measured on the
  joined note. It is still absent from a record with no text at all — a bare image, and a
  call cancelled before it returned — which is what `UsageRecord` has always documented and
  what `docs/telemetry.md` now says instead of claiming the field is always present.
- **`make build` broke `make test` on the next invocation.** It ran `uv sync --no-dev`
  against the shared `.venv`, which uninstalls pytest, pytest-timeout, flask and ruff. The
  damage was not a clean failure: `uv run pytest` finds no pytest in the project
  environment, falls through to the first one on `PATH`, and collects this repository under
  a foreign interpreter's site-packages — reported as
  `ModuleNotFoundError: No module named 'fastmcp.server.providers'` plus two
  `Unknown config option` warnings for the timeout keys, all of which look like a
  dependency regression and none of which are. `build` now syncs into its own
  `.venv-build`, the pattern `test-oldest` already used, and `lint`, `format`, `test` and
  `test-oldest` each pass `--extra dev` so uv restores anything missing rather than
  deferring to `PATH`.

### Security

- **A password typed into a page was written to disk in clear text.** 573 fill values were
  on disk unredacted and there was no redaction anywhere in `src/`; a password under 200
  characters was fully logged. It would have got worse the moment a workflow read these
  logs to generate a skill, since the secret would have been copied into the generated
  file. The value of a fill is now replaced by `<redacted N chars>` when the resolved field
  is an `<input type="password">`, when ANY of the names it carries — aria-label, bound
  `<label>`, placeholder, form name — or the selector that addressed it matches a short
  closed list of whole words in English and French, or when the call resolved nothing at
  all. That last case is the retry an agent makes after a navigation invalidated its uids,
  which is exactly when a password gets re-typed; the value reached no page, so it is worth
  nothing to a future recipe while a leak is permanent. All 4 names are tested rather than
  the one that wins the race to be the recorded `label`, because
  `<label for="cvc">Security code</label>` hides a `cvc` that nothing else would catch.
  Redaction runs before truncation, is decided per field (one password in a 6-field form
  does not cost the other 5 their values), and deliberately does not fire on search terms,
  filters, dates or discount codes: those are the substance of the log, and `code`, `key`
  and `pin` are not on the list for that reason — "PIN Code" is the Indian postal code and
  sits on every shipping form. The residual false positives it does accept are named in
  `docs/telemetry.md` rather than hidden, along with the field content that still reaches
  the log by other routes.
- **A password was rendered in clear text by `snapshot`, by `find`, by the observation
  a fill appends and by `get_element(prop="value")`.** The walk printed a `value=` part for
  any input holding a value, the password type included, so
  `fill(uid=<password>, observe="snapshot")` wrote the secret into `result` at offset 225
  of the note — redacted out of `args` by the change above and put straight back by the one
  that raised the result ceiling from 200 to 10,000 characters, which is where that byte
  used to be cut off. The value of an `<input type="password">` is now elided at every
  renderer that can reach it, as `<redacted N chars>`: the first 3 share one walk, and the
  property read answers off its own script in the page, which runs in the page's global
  scope and so restates the rule rather than sharing it. An agent asking what a password
  field holds has no more business with the cleartext than the log does. The elision
  covers both shapes the walk renders: the input's own line, and the description a
  `<label>` carries on behalf of a control the page hides behind it.
- **Two ways the secret test could be handed the wrong names.** It reads every name a
  field carries, joined into one string, and both halves of producing that string were
  defeasible. The names were capped at 80 characters BEFORE the test saw them, which is
  the cap the rendered line owes, not the test: "Pour valider la création de votre compte,
  veuillez confirmer ci-dessous votre mot de passe" says "passe" at offset 85, so the one
  word making the field a secret was cut off and the password was logged in clear. And the
  names were assembled with `Array.prototype.join`, which resolves on the page's own
  prototype at call time: a page replacing it decided what the test read. Both are fixed
  where they happen — the cap now applies only to the name that is rendered, and every
  string the bundle builds is concatenated in the index loop that built it — and the
  source guard that exists to catch the second now covers `join` and every other array
  method a string does not also carry, which is why it never fired.
- **The same array-method defect, unguarded, in the read behind
  `get_element(prop="value")`.** The guard above scanned the top level of `dom/js/` only,
  so `dom/js/reads/` was outside it — and that is the MORE exposed half, not the less: a
  read is compiled by the page's own `Function` constructor and runs in the page's global
  scope, where not even the boot-time built-in table is reachable. `value.js` decided
  inside `els.map(...)` whether an `<input type="password">` has its value elided, so a
  page replacing `Array.prototype.map` chose what a security-relevant read returned;
  `text.js` collected a `<select>`'s selected options with `for...of`, `push` and `join`;
  `style.js` consulted the computed-style enumeration through
  `Array.prototype.indexOf.call`. All 6 reads now collect by index into
  `out[out.length] = x`, the redundant `toLowerCase` on the IDL-lowercased `el.type` is
  gone, and the guard recurses into the subdirectory. Its banned-method list also grew the
  6 `Array.prototype` names it was missing (`findLastIndex`, `copyWithin`, `toSorted`,
  `toReversed`, `toSpliced`, `with`) and now states why `entries`, `keys` and `values` are
  deliberately not on it.
- **A fill quoted the value it was given back into its own message.** Redaction
  rewrites `args`; `result` and `error` are written as the tool produced them, and three
  messages interpolated the typed text: a `<select>` matching no option, a checkbox handed
  something that is not a state, and — on the success path — the `Selected '<value>' in
  <select>` a `<select>` returns. All three are reachable on a field the word list calls
  a secret — `fill(uid=<select name="token">, value=<credential>)` — so the value redacted
  out of `args` was written back onto the same line in clear. The 2 refusals name the
  length instead (`<N chars>`) and keep their diagnosis, the options that do exist and the
  states that are accepted; the success line now echoes the option the PAGE matched, as the
  page spells it, which is page content rather than caller input and also tells the reader
  what was actually picked when the match was case-insensitive. Fixed in `dom/`, which
  cannot tell a credential from a search term (that test reads the 4 names a field carries
  and lives a layer out), so it now writes no caller-supplied value into any message at all.
  The list of options that refusal names is bounded too, at 20 plus a `... (N more)` tail:
  capping each label at 80 characters bounds a LABEL and not the list, so a `<select>`
  holding thousands of options was still a page sizing a line that is handed to the model
  and kept whole as the record's `error`, which nothing truncates.
- **A captured request handed over the credentials of the profile that made it.**
  `get_network_request` rendered the raw request and response headers — `Cookie`,
  `Set-Cookie`, `Authorization`, `Proxy-Authorization` — and the raw POST body straight
  into its result, which is also the record's `result`. Pre-existing, but this release
  made it real: the POST section sits after a header block that routinely runs past 200
  characters, so raising the result ceiling to 10,000 turned a body that was usually cut
  off before it reached disk into one recorded in full, and a sign-in body carries the very
  password the redaction above was built to remove. The `Cookie` of a profile signed in by
  hand is a session credential, and this product's whole premise is that such a profile
  exists. Those 4 header values are now elided at the renderer — name and
  `<redacted N chars>` kept, matched without regard to case since Firefox lowercases them —
  and a POST body loses its credential-looking FIELDS one at a time, judged by name against
  the same closed word list a typed value is judged by and substituted in place, so every
  other byte of the payload is rendered exactly as captured. Dropping or truncating the
  body was rejected: inspecting an API payload is what the tool is for. What is
  deliberately still rendered whole — an unparseable body shape, the response body, the
  URL — is named in `docs/telemetry.md` rather than left to be discovered.

## [0.3.5] - 2026-08-06

What a read-only audit found once 0.3.4 was out. Nothing here was reported by a user, and
most of it could not have been: the sharpest 2 are a page able to defeat a tool it asked for
help from, and a server that refuses to start if you copy the example file this project ships.

### Fixed

- **A page could defeat `strip_scripts` and keep its own scripts in the answer.** `get_html`
  was the only tool that built its own page script instead of going through the element layer,
  so `document.querySelector`, `cloneNode`, `querySelectorAll` and `NodeList.prototype.forEach`
  all resolved on the page's own prototypes when the call was made. Replacing that last one
  with a no-op made the removal pass visit nothing, and the caller was handed the `<script>`
  elements it had asked to have removed. The read is now an `extract` operation in the bundle:
  7 more accessors are captured at boot, and the removal is an index loop with no array method
  at all. The marker test drives `get_html` 3 ways now, which is the coverage hole that let
  this live: that test walks every path consuming a uid, and `get_html` consumes none.
- **Copying `.env.example` stopped the server from starting.** An empty value meant "unset"
  for 11 of the 13 variables and an error for the other 2, and the shipped example ships 1 of
  those 2 empty, under a header promising every variable is optional. The failure landed
  before logging exists, so a client saw a dead server and no reason. Blank now means unset
  everywhere except the 2 places where blank means something real, and those 2 are named in
  the file, in the docs, and in a test that fails if a third joins them quietly.
- **A typo in `CAMOUFOX_BINARY` changed which browser build every other tool on the machine
  got.** A path that does not exist read as "no browser present", so the cold-install branch
  ran, downloaded the pinned build and activated it machine-wide, an activation the launch
  then ignored because an explicit binary wins. The error at the end never named the bad path.
  It is refused up front now, naming both the path and the variable.
- **A GeoIP download failure refused the start and blamed the browser.** It sat in the same
  `try` as the browser install, so a MaxMind hiccup produced "build 152.0.4-beta.28 is not
  present" about a build sitting on disk. GeoIP matters only when a proxy is configured, so a
  proxy-less user was blocked by an asset they never use. It is fail-open now, warns, and
  leaves the stamp unwritten so the next check retries instead of parking for 24h.
- **Proxy URLs lost IPv6 brackets and never decoded credentials.** `http://[::1]:3128` became
  `http://::1:3128`, which no browser can parse, and a password written `p%40ss` was sent
  literally, so every request 407'd. Percent-encoding is the only way to spell a password
  containing `@` or `:`, so those passwords could not be configured at all. Both directions of
  a proxy URL live in 1 module now. A literal `%` must be written `%25`, which the URL grammar
  always required, and that cost is pinned by its own test.
- **`CAMOUFOX_VIEWPORT=1280x0` passed startup validation** and failed at every session launch
  with a message about something else.
- **A navigation could keep the old page's requests and drop the new page's.** The rotation
  boundary added in 0.3.4 was set by any request of type "document", an iframe's included, so
  an embed loading mid-page moved the boundary and the next navigation retired the wrong side.
  The boundary is the tab's own main frame now, checked against Playwright's source and against
  the pinned build rather than assumed, and a request whose frame cannot be read counts as not
  the tab's rather than raising inside a listener.
- **`fill_form` turned every failure into a `ValueError`.** A timeout stopped rendering as
  `Timeout: ...`, and an off-contract exception stopped leaving a traceback in the server log,
  which is exactly how a `UnicodeDecodeError` went unexplained for a month. The field index it
  adds is kept, by rewriting the exception's arguments instead of replacing it.
- **`click_at` with an empty `points` list reported a click that never happened**, answering
  `Clicked 0 points at`.
- **`scroll` launched a browser before rejecting a bad `direction`**, and never rejected it at
  all on the uid path.
- **A corrupt `daemon.endpoint` file crashed the proxy** instead of reading as no daemon: the
  JSON guard caught a bad parse but not a valid parse of the wrong shape.

### Changed

- **The release suite runs on both Python versions this project supports**, 3.12 and 3.13, in
  parallel and without fail-fast, and the upload still waits for all of it. The 2 have already
  differed in a way that hid a defect for a whole release, so testing 1 of them was testing
  half of what people install. `make test-oldest` runs 3.12 locally.
- **5 assertions that could not fail were replaced**, each replacement proved able to go red by
  breaking the thing it is about on purpose. The largest was a session-id check satisfied by
  any non-empty string, the word "Error" included, which left a cookie-persistence claim
  asserting nothing. Another found that 1 of the 3 channels watching for an unread asyncio
  error is blind by construction, because pytest's logging plugin takes the record before it
  reaches the file descriptor being watched. That channel is gone and the reason is written
  where the claim is.
- **The `tools/list` budget was re-measured at 22,592 chars**, up 329 from the recorded 22,263.
  The tool count never moved, so the extra bytes are parameters an earlier release added
  without re-measuring; the 5 percent margin absorbed it, which is the margin working and also
  why nobody noticed. The number records what is actually served now.
- Test guardrails smaller than the product's own budget now import that budget instead of
  copying a number: a daemon has 10 seconds to tighten its socket and the test waited 2, so a
  loaded machine could fail a daemon that was still inside its contract.
- Dead code removed with a per-name search behind each removal: 3 re-exports in the element
  facade, an unused field left by the endpoint split, and a paging pair on the console monitor
  no caller ever reached. The atomic advert write, which sets `0o600` on a control channel's
  address, existed in 2 copies and is 1 now: a security property in 2 places drifts.
- Two comments stating the opposite of their code were corrected, both in buffer-retirement
  logic. A comment that lies about a pruning rule is how the defect above comes back.

## [0.3.4] - 2026-08-06

A release pipeline that runs the tests, a suite that no longer measures the machine, a daemon
that cleans up after itself, and a network listing that stops losing the page's own first
request.

0.3.1, 0.3.2 and 0.3.3 carry the same work and were all tagged, and none of them reached
PyPI: the pipeline ran the entire suite each time and stopped, on the daemon defect, then the
marker test, then the network rotation below. Each of those was a real defect that thousands
of green runs on a workstation had never caught, so the 3 tags stay where they are as the
record of what the gate is for, and this is the version you can install.

### Added

- `CAMOUFOX_BUNDLED_ADDONS`, `false` to launch without the extensions Camoufox ships. It
  defaults to `true`, so nothing changes unless you set it. It exists because the marker test
  needs a browser with no extension in it at all, and because until now there was no way to
  ask for one: `CAMOUFOX_ADDON_URLS` only ever governed this project's own list.

### Changed

- **The marker test says what it saw.** A release run failed on it with
  `['childList:', 'childList:', 'childList:']`: 3 mutations, and nothing about whose they
  were, which is unactionable for the one test carrying this project's central claim. Every
  record now names its target (node name, id, class) and, for a child-list change, the nodes
  added and removed. That alone named the culprit on the very next run, in 1 line, and it is
  the second entry under Fixed. The probes also refuse any `readyState` but `complete`, since
  an unfinished parse appends the rest of the page while they record and those appends cannot
  be told from a leak of ours by count. That was not the cause here, but it was a second way
  to be misled and it is closed. Nothing was relaxed, the tally still has to be empty. The
  instrument moved to `tests/probes.py` and the driver artifact it pins to
  `tests/test_driver_footprint.py`, the module having outgrown 300 lines.
- **Publishing now runs the whole test suite first.** 0.3.0 was uploaded on the word that
  the suite passed locally: the workflow built and published without executing a single
  test. It is now build, then the entire suite against a real browser on the runner, then
  the upload behind a manual approval, each stage needing the one before it. The build also
  refuses a tag that disagrees with the version inside the wheel, and `workflow_dispatch` is
  gone, since it allowed publishing from any branch and emptied "tags only" of its meaning.
- **No test waits a duration before asserting.** 6 assertions in this project measured how
  fast a machine is rather than whether the code was right, and each cost a debugging cycle:
  a latency compared against an absolute threshold, a 1 second sleep before checking a
  captured request, an advert asserted gone the instant a process was reaped, 2 tools
  compared on a page where neither actually waited, a race asserted to resolve the way the
  product explicitly does not promise, and 1 that could not fail at all. Every wait is now a
  poll for the condition being asserted, with a deadline only as a guardrail, through a
  single `poll_until`. About 18 seconds of unconditional sleeping went with them.
- Several tests were strengthened while being made deterministic rather than merely
  stabilised: the network tests now target the request the action caused instead of
  whichever landed first on the tab, the double-click test counts the events the page
  received instead of matching a word in the result string, the infinite-scroll test waits
  for the page to be quiescent so its baseline is a settled number, and 8 assertions of the
  form "error appears somewhere in the output" now pin the exact one-line error.
- Downloaded addon archives are cached under `<data_dir>/addons/` (`CAMOUFOX_DATA_DIR`)
  instead of `~/.cache/camoufox-mcp/addons`, like every other path the server owns. They
  are re-downloaded once.
- One cold browser launch no longer blocks the first call of every other profile: launch
  locking is per profile, which matters most in daemon mode.

### Fixed

- **`list_network_requests` answered "No network requests captured." for a page whose request
  it had already recorded and seen answered.** On the first navigation of a session, and only
  there, because that navigation is what spawns the content process. The commit reaches us
  from that process while the requests reach us from the browser's HTTP layer, 2 sources with
  no order between them, so a page's load-time fetch could be recorded, answered 200, and
  then retired wholesale by a commit arriving up to 380 ms later. The listing hides preserved
  entries by default, and a page that fills its viewport issues no second fetch, so the answer
  stayed empty for good. The network monitor now retires by entry id, keeping everything
  recorded after the navigation's own document request, and prunes only what it retired, so a
  request still in flight when a late commit lands still gets its status instead of reading
  `pending` for ever. The interleaving is now a fixture rather than a race: a fake tab emits
  the protocol events in the damaging order, and that test fails on the old code.
- **The marker test counted uBlock Origin's DOM writes as ours.** It failed a release run with
  3 `childList` records, which were uBO adding a `<script>` to `<head>`, removing it, and
  removing its text node. The test's own docstring claimed the session ran with no browser
  extension, which was false: Camoufox adds its addons on every launch and nothing could
  opt out. The session now launches with none, proved by reading the profile's extension
  records rather than by trusting a green test, and a second control proves that reading finds
  uBO when it is left in.
- **The daemon never withdrew its address advert, on any exit.** Not intermittently: the
  code that removed it had never run. Every exit the daemon has is a signal, since the idle
  watchdog and `/shutdown` both raise SIGTERM at themselves, and uvicorn answers a signal by
  shutting down, restoring the handler installed before it, then re-raising. The process
  died inside the serve call, so nothing after it ran, `finally` blocks included. Withdrawal
  now happens in a handler installed around that call, which is the one uvicorn restores,
  and the proof that the advert is this daemon's own is read back synchronously at `bind()`
  instead of coming from a background task that a signal could cancel before it produced
  one. Left behind, a stale advert costs the next proxy a failed probe before it recovers.
- The test that should have caught the line above passed here and failed only on the release
  runner, because Python 3.13's asyncio unlinks a closed Unix socket by itself and 3.12 does
  not. The assertion was being satisfied by the standard library rather than by this
  project's code, on 1 of the 2 interpreter versions it supports. Both advert files, the
  socket and the pointer, are now asserted on.
- A duplicated block at the head of a test module shadowed its own helpers, so 3 functions
  were defined twice and the first definition of each was dead.
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

[Unreleased]: https://github.com/agelyhq/mcp-camoufox/compare/v0.4.3...HEAD
[0.4.3]: https://github.com/agelyhq/mcp-camoufox/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/agelyhq/mcp-camoufox/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/agelyhq/mcp-camoufox/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/agelyhq/mcp-camoufox/compare/v0.3.5...v0.4.0
[0.3.5]: https://github.com/agelyhq/mcp-camoufox/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/agelyhq/mcp-camoufox/compare/v0.3.0...v0.3.4
[0.3.0]: https://github.com/agelyhq/mcp-camoufox/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/agelyhq/mcp-camoufox/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/agelyhq/mcp-camoufox/releases/tag/v0.1.1
[0.1.0]: https://github.com/agelyhq/mcp-camoufox/tree/1798b33940fd8d0c51c3491db2d98f6d5a79b8a2
