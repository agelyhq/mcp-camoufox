# TODO

Future work and standing decisions only. Everything from the 2026-07-16 token-audit
backlog (get_html scoping, one-line errors, telemetry measurability, `observe`,
selector-based click/fill, `wait_for` predicate, screenshot `max_width`, snapshot
caps, `click_at` batch, evaluate intent telemetry, the shared daemon) has shipped.

## Tool-surface review (decided 2026-07-16)

Remove/merge **nothing** now, despite ~half the tools at zero usage: MCP schemas sit
in the prompt-cached prefix (~0.1x after turn 1) and recent Claude Code defers them
via ToolSearch, so the schema-token economics don't hold; `handle_dialog` and
`upload_file` have no `evaluate` fallback; `performance_summary` is W3C
Navigation-Timing (Firefox-native, in scope). Enriched telemetry (`result_chars`,
image tokens, evaluate `intent`/`script_hash`) shipped 2026-07-16, so the ~30-day
data-collection clock **starts now** — re-review the surface after ~30 days of that
data before deciding any removal.

## Parity watch — closed (2026-07-16)

`resize_page` and `emulate` (the only non-CDP gaps vs chrome-devtools-mcp v1.6.0)
will **not** be implemented as specified. Camoufox has no equivalent primitive:
window resize is deliberately blocked, and Playwright's `set_viewport_size` on
Firefox moves only the content viewport while `screen.width/height` stay at the
launch fingerprint — reintroducing the exact viewport-vs-screen mismatch Camoufox's
launch-time coherence exists to prevent. The image-token motivation is already served
by the creation-time knobs (`CAMOUFOX_VIEWPORT`, `viewport_width/height`). CPU/network
throttling has no Firefox equivalent at all. If ever revisited, any viewport lever
must be **creation-only** (rejected on an active profile) and **shrink-only within the
launch-fingerprinted screen** — never a live CDP-style resize. Reopen only if a
concrete use case demands post-launch geolocation/UA switching, or if Camoufox later
exposes a safe constrained-resize primitive.

## Daemon hardening (post burn-in)

- Flip the `CAMOUFOX_DAEMON` default to `true` once the opt-in daemon has burned in
  under real multi-conversation usage.
- Crash recovery is v1: the daemon is ensured only at proxy startup, so a daemon that
  dies mid-conversation is not respawned until the next conversation starts. Add a
  mid-conversation health re-check / respawn if that proves painful in practice.
- Known rare race on the identity-**mismatch** path: if a session lands between the
  health probe and `/shutdown`, the `409` + timeout path can unlink a **live**
  daemon's socket. Fix idea: inode-ownership-aware cleanup (only unlink the socket
  the doomed daemon actually created) instead of blind removal.
- AF_UNIX socket paths are capped near ~108 chars; a very long `CAMOUFOX_DATA_DIR`
  would overflow `<data_dir>/daemon.sock`. Fix idea: relocate the socket under
  `XDG_RUNTIME_DIR` (short, per-user) while keeping profiles under the data dir.

## Display modes

Per-launch `DISPLAY` isolation is not built. Confirmed mechanism: Camoufox's `virtual`
mode spawns one Xvfb per launch and mutates the **process-global** `os.environ`
`DISPLAY` (it defaults env to a reference of `os.environ`), so a later visible session
in the same process inherits the throwaway Xvfb display instead of the real desktop.
Fix idea: pass an explicit per-launch `env` dict to Camoufox so each session pins its
own `DISPLAY` — required if a single process (or the daemon) must ever run mixed
display modes simultaneously.

## setDefaultViewport incident (resolved 2026-07-16)

Root cause of the 2026-07-15 launch failures: an unbounded transitive Playwright
drifted ahead of the installed Camoufox binary's Juggler schema and emitted a
`Browser.setDefaultViewport` payload (with `viewport.isMobile`) the binary rejected —
a cross-version protocol mismatch, not a bug in our launch code (it self-healed once
the binary auto-updated). Fixed by pinning `camoufox<0.5` and `playwright>=1.58,<1.59`
together in `pyproject.toml` so the two can never drift apart. When bumping either,
bump both consciously and re-run the full E2E suite; a `no_viewport=True` launch kwarg
was considered but deferred (it makes the inner size fingerprint-random, changing
screenshot dimensions and threatening E2E determinism).
