# 🔗 Shared daemon mode

By default every MCP server process launches and owns its own browsers. Set
`CAMOUFOX_DAEMON=true` and the `mcp-camoufox` entry point becomes a thin proxy to a
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
mcp-camoufox-daemon          # or: python -m camoufox_mcp.daemon
```

## 🔒 The control channel

The daemon speaks HTTP, but never on a routable port. How it is bound depends on the
platform: `daemon/endpoint.py` holds the abstraction and picks the strategy,
`daemon/endpoint_unix.py` and `daemon/endpoint_loopback.py` implement the 2 of them.

**POSIX** uses a Unix domain socket under `$XDG_RUNTIME_DIR`, named after a digest of the
resolved data directory, falling back to `<data_dir>/daemon/daemon.sock` when that variable
is unset. Its parent directory is created `0700` so the socket is never world-reachable
during the brief window before it is itself tightened to `0600`.

It lives there rather than in the data directory because a socket address is a fixed buffer
capped near 108 bytes: a long `CAMOUFOX_DATA_DIR` used to make the daemon unbindable, and
the failure surfaced as an opaque OS error rather than as an explanation. The length is now
validated before binding and refused with a message naming the limit and the offending
path. The digest is not decoration: once the address stops containing the data directory,
2 servers configured with different data directories would otherwise meet on 1 control
channel and drive each other's profiles.

Discovery stays anchored in the data directory. A running daemon records the address it
actually bound in `<data_dir>/daemon/daemon.address`, and a proxy reads that pointer before
deriving anything, because 2 processes do not always share an environment and a proxy
lacking `XDG_RUNTIME_DIR` would otherwise start a second daemon on the same profiles.

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

## 🚪 How it withdraws its advert

Every exit the daemon has is a signal: the idle watchdog and `/shutdown` both raise
SIGTERM at themselves so uvicorn shuts down gracefully. Uvicorn then restores the signal
handler that was installed before it and **re-raises** the signal it caught, so the
process dies inside the serve call and nothing written after it ever runs, `finally`
blocks included. The advert is therefore withdrawn from a signal handler installed around
that call (`lifecycle.cleanup_on_termination`), which is precisely the handler uvicorn
restores, and which re-raises under the default one so terminating still terminates.

What it removes is only ever its own advert, proved by the identity read back at `bind()`
when this daemon published it (on POSIX the inode of `daemon.address`, replaced atomically
at every publication). No proof, no unlink: an advert on disk may belong to a daemon that
is still serving, and taking it would leave that daemon's browsers running and unreachable.

Worth knowing, because it hid the bug for a release: Python 3.13's asyncio unlinks a closed
Unix socket by itself and 3.12 does not, so a daemon withdrawing nothing still looked clean
on 3.13. The tests assert on every advert file, the socket and the pointer both.

## 🔄 Code reloads

The daemon advertises its version and code path on `/health`. A proxy running
different code will shut down and respawn an **idle** daemon that does not match. If
the mismatched daemon still holds live sessions, it is reused with a warning and never
killed, because killing it would destroy someone's authenticated browser.

The proxy caches no tool list, so a code change is picked up at the next idle respawn.

## 🔁 When the daemon dies

Recovery reacts to 2 different failures, because they look nothing alike.

A daemon that dies **between** calls makes the next request raise, and the proxy respawns
once, with a bounded retry and a 5 second cooldown so a burst of concurrent failures shares
1 respawn.

A daemon that dies **while a request is in flight** raises nothing at all: the response
simply never arrives, and no read timeout rescues it. So the proxy watches every
outstanding request and probes the control channel between intervals. It cancels the call
only on proof of death, meaning a refused connection or a withdrawn advert, confirmed twice
2 seconds apart. A timeout is deliberately not proof: a cold browser launch can block the
daemon's event loop for longer than a probe, and cancelling a healthy call is worse than
waiting for a slow one. Detection costs about 2.4 seconds in practice.

Either way the live browsers are gone, and the error says so rather than pretending the
session survived. The failed request is never replayed: it may have had side effects.

The limit that remains, stated: a daemon that is alive but wedged, still accepting
connections and never answering, is not detected. Distinguishing it from a daemon busy
launching a browser needs a much longer bound, and that is a separate decision.

## ⚠️ Known limits

A daemon that is alive but wedged, still accepting connections and never answering, is not
detected. Telling that apart from a daemon busy launching a browser needs a much longer
bound than the one the watchdog uses, and a slow launch is far more common than a wedged
loop, so the trade is deliberate.

The Windows control channel is exercised by tests that drive its endpoint class on Linux.
The class is covered; the platform is not, on this machine.

The default is `false` for now. It will flip once the opt-in version has run long enough
under real multi-conversation use.
