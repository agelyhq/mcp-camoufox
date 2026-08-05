# ⚙️ Configuration

Everything is configured through environment variables, set in your MCP client's
config. There is no config file. `config.py` is the only module that reads the
environment, so this list is complete.

A copy of it lives in [.env.example](../.env.example).

## 📋 Variables

| Variable | Default | What it does |
|---|---|---|
| `CAMOUFOX_HEADLESS` | a visible window | `true` (headless), `virtual` (Xvfb, Linux only), `false` (visible). See below. |
| `CAMOUFOX_PROXY` | none | `http://user:pass@host:port`. Parsed into a Playwright proxy and turns on GeoIP, so timezone, locale and geolocation follow the exit IP. |
| `CAMOUFOX_DATA_DIR` | OS user data directory | Where profiles and logs live. |
| `CAMOUFOX_VIEWPORT` | Camoufox default | Window size, for example `1280x720`. |
| `CAMOUFOX_FINGERPRINT_OS` | random | `windows`, `linux` or `macos`. |
| `CAMOUFOX_LOCALE` | Camoufox default | Browser locale, for example `en-US`. |
| `CAMOUFOX_ADDON_URLS` | built-in defaults | Comma-separated list of addon URLs, replacing this project's defaults. Camoufox loads uBlock Origin into every browser it launches on its own, and no value here removes it: that is `CAMOUFOX_BUNDLED_ADDONS`. |
| `CAMOUFOX_BUNDLED_ADDONS` | `true` | Set `false` to launch without the addons Camoufox bundles itself (uBlock Origin), which is the only way to remove them. Leave it on unless you need a browser holding nothing you did not put there. |
| `CAMOUFOX_AUTO_UPDATE` | `true` | Set `false` to skip the startup browser and GeoIP update check. |
| `CAMOUFOX_HUMANIZE` | off | Maximum cursor travel time in seconds, for example `1.5`. Read the warning below before enabling. |
| `CAMOUFOX_BROWSER_VERSION` | the tested build | Pins the browser build, for example `152.0.4-beta.28`. Set it to `latest` to follow whatever upstream published last, which is how an install can change Firefox major version without any change on your side. |
| `CAMOUFOX_BINARY` | Camoufox's own cache | Explicit path to a Camoufox executable. |
| `CAMOUFOX_DAEMON` | `false` | `true` routes everything through a shared daemon. See [daemon.md](daemon.md). |
| `CAMOUFOX_DAEMON_TTL` | `1800` | Daemon idle shutdown, in seconds. Only meaningful with the daemon on. |

## 🪟 Window modes

`CAMOUFOX_HEADLESS` matters more than it looks, because headless browsers carry
detection tells that a windowed browser does not.

- **unset or `false`**: a real visible window. Best for anti-detection and required
  when you need to sign in by hand. Needs a working desktop GL stack.
- **`virtual`**: a real windowed browser inside an Xvfb display. Invisible to you, but
  the page sees a normal window. This is the best of both and what the test suite
  runs. **Linux only**: Xvfb does not exist on Windows or macOS, and the launch is
  rejected there rather than silently falling back.
- **`true`**: genuine headless. Use it on Windows and macOS, in containers, and in CI.

Mixing modes in one process used to be a trap: Camoufox writes the throwaway Xvfb
`DISPLAY` into the environment it was handed, and it defaults that to the live process
environment, so a visible session started after a virtual one inherited a 1x1 display
instead of the real desktop. Each launch now gets its own copy of the environment, so the
modes no longer interfere and a test pins it.

## 🖱️ The humanised cursor

`CAMOUFOX_HUMANIZE` enables Camoufox's human-like mouse movement, which is real
anti-detection value. It is off by default because it can wedge the browser with no
timeout and no way back.

The mechanism: synthesised mouse events are serialised on a dispatch chain shared by the
whole browser process, and each one waits for the renderer to acknowledge it. A missed
acknowledgement never arrives, so the chain never advances and every later input event
queues behind it forever. The 2 known triggers were fixed upstream in July 2026, and we
still saw the freeze afterwards on a build carrying both fixes, so what is left is the
residual class rather than the triggers. It has happened in real use, not only under test:
1 click ran for 33 minutes.

Enable it only if you want it and can tolerate a hang. The full reasoning, including the
upstream tracking, is in [decisions.md](decisions.md).

## 🎛️ Per-session options

A few settings can be overridden per profile, on the `navigate` call that creates the
session:

```
navigate(profile="au", url="https://example.com",
         fingerprint_os="windows", locale="en-AU",
         viewport_width=1280, viewport_height=720,
         block_images=true, headless="virtual")
```

These apply **only when the session is created**. Calling `navigate` again on a running
profile ignores them and says so in the result. To change them, `close_session` first.

That restriction is deliberate: the fingerprint is generated as a coherent whole at
launch, and changing one part of it afterwards is what makes a browser detectable.
`fingerprint_os` is validated against `windows`, `linux` and `macos`, and anything else
is an error.

## 📁 Where files go

With `CAMOUFOX_DATA_DIR` unset, the base directory is the platform user data directory:

| Platform | Path |
|---|---|
| Linux | `~/.local/share/camoufox-mcp/` |
| macOS | `~/Library/Application Support/camoufox-mcp/` |
| Windows | `%LOCALAPPDATA%\camoufox-mcp\` |

That directory is `camoufox-mcp` while the package is `mcp-camoufox`, and the mismatch is
deliberate. The package had to be renamed because `camoufox-mcp` belongs to someone else on
PyPI. Renaming the directory too would have stranded every existing profile, and a profile
is a login somebody signed into by hand, so it stayed where it is.

Inside it:

```
profiles/<profile>/   persistent browser context, one per profile name
logs/<profile>.jsonl  telemetry, one line per tool call
logs/_server.jsonl    server lifecycle records
addons/               downloaded extension archives, shared by every profile
daemon/               socket, lock and log, only when the daemon is on
```

Profile directories are created owner-only. They hold live session cookies for every
site you signed into, so treat them like credentials: see [profiles.md](profiles.md).
