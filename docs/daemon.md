# 🔗 Shared daemon mode

By default every MCP server process launches and owns its own browsers. Set
`CAMOUFOX_DAEMON=true` and the `camoufox-mcp` entry point becomes a thin proxy to a
single local daemon that owns all of them, so several conversations share one set of
sessions, one auto-update and one process.

With the variable unset, none of this code runs and the behaviour is exactly as before.

## 💡 Why you might want it

- Several conversations reusing the same signed-in sessions, instead of each holding
  its own and hitting `ProfileInUseError`.
- One browser process instead of N, which matters because each one is a full Firefox.
- One auto-update check instead of N.

Profile isolation is unchanged. Sessions are still keyed by profile name; the daemon
shares the process, not the profiles.

## ⚙️ How it works

The first proxy to start spawns the daemon detached, under a spawn lock, cleaning up
any stale socket and polling `/health` until it is ready. Every MCP call is then
forwarded to it over a private HTTP channel. Auto-update, telemetry and the session
manager live only in the daemon. The proxy owns none of them.

To debug, run it in the foreground:

```bash
camoufox-mcp-daemon          # or: python -m camoufox_mcp.daemon
```

## 🔒 The control channel

The daemon speaks HTTP, but never on a routable port. How it is bound depends on the
platform, decided at import time in `daemon/endpoint.py`.

**POSIX** uses a Unix domain socket at `<data_dir>/daemon/daemon.sock`. Its parent
directory is created `0700` so the socket is never world-reachable during the brief
window before it is itself tightened to `0600`.

**Windows** has no Unix socket support in asyncio, so it binds a `127.0.0.1` loopback
socket on an ephemeral port. Any local process can reach loopback, so every request
must carry a per-daemon bearer token. The daemon advertises `{host, port, token}` in a
`0600` `daemon.endpoint` file, and unauthenticated requests are rejected.

This is a real difference in security posture, worth knowing: on POSIX the boundary is
a file mode, on Windows it is a token, because directory permissions there are weaker.
The spawn lock is cross-platform (`filelock`).

## ⏱️ Lifetime

The daemon shuts itself down after `CAMOUFOX_DAEMON_TTL` seconds (default 1800), but
**only** when there are zero active sessions and zero in-flight requests. It never
closes a live browser to meet a timeout. A long-running session keeps it alive
indefinitely, which is the intended behaviour.

## 🔄 Code reloads

The daemon advertises its version and code path on `/health`. A proxy running
different code will shut down and respawn an **idle** daemon that does not match. If
the mismatched daemon still holds live sessions, it is reused with a warning and never
killed, because killing it would destroy someone's authenticated browser.

The proxy caches no tool list, so a code change is picked up at the next idle respawn.

## ⚠️ Known limits

Crash recovery is minimal: the daemon is only ensured when a proxy starts, so one that
dies mid-conversation is not respawned until the next conversation begins. Tracked in
[#4](https://github.com/agelyhq/mcp-camoufox/issues/4).

There is also a rare race on the identity-mismatch path, tracked in
[#2](https://github.com/agelyhq/mcp-camoufox/issues/2), and a socket path length limit
on POSIX, tracked in [#3](https://github.com/agelyhq/mcp-camoufox/issues/3).

The default is `false` for now. It will flip once the opt-in version has run long
enough under real multi-conversation use.
