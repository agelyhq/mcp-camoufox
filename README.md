# 🦊 mcp-camoufox

**The browser MCP server that does not get blocked.**

Cloudflare challenges, anti-bot walls, sign-in pages that refuse an automated browser:
your agent runs into them, and you end up finishing the job by hand. This one drives
[Camoufox](https://camoufox.com), an anti-detect Firefox build, so pages treat it as a
normal browser and the agent gets through.

Several months of daily use, on Linux and Windows.

## 🧱 The problem

Browser automation works right up until a site decides it is a bot. Then you get a
challenge page, an empty result, or a sign-in that will not complete, and the agent is
stuck. It happens on exactly the sites that have real work in them:

- **☁️ Cloud consoles.** Plenty of GCP and AWS tasks simply do not exist in the CLI.
  You have to click them. But the Google sign-in refuses an automated Chrome, and a
  personal `@gmail.com` account is refused where a Workspace one might pass.
- **🛠️ Everything else with a console.** Ordering a domain at OVH, pointing DNS,
  setting passwords, Google Analytics, Firebase, Tag Manager. Long tasks made of small
  clicks, with no API behind them.
- **🚧 Sites with an aggressive wall.** LinkedIn, Meta Business, and anything sitting
  behind a Cloudflare challenge.
- **✈️ Planning a trip.** Booking, Tripadvisor and Airbnb all block automation, and
  they are exactly where you want an agent doing the comparison work.
- **🔐 Your own app.** Testing an authenticated flow without writing a test-only login
  bypass first.

Stealth plugins do not solve this. They hide the automation from JavaScript, and the
hiding is itself detectable. Camoufox takes the other route: Firefox patched at the C++
level, so the automation agent is sandboxed away from the page and the fingerprint is
coherent before any page script runs. Details in [docs/anti-bot.md](docs/anti-bot.md).

## 📦 Install

```bash
claude mcp add camoufox -e CAMOUFOX_HEADLESS=virtual -- \
  uvx --from git+https://github.com/agelyhq/mcp-camoufox camoufox-mcp
```

Or in any MCP client's config:

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/agelyhq/mcp-camoufox", "camoufox-mcp"],
      "env": { "CAMOUFOX_HEADLESS": "virtual" }
    }
  }
}
```

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/). The browser downloads itself
on first use. `virtual` runs a real windowed browser inside Xvfb, invisible to you and
harder to detect than headless; it is Linux only, so use `true` on Windows and macOS.

Then just ask:

```
Open the pricing page of <a site that usually blocks you> with the
profile "research" and summarise the plans.
```

## ✨ What you get

**🛡️ Sites stop blocking you.** Camoufox patches Firefox itself rather than injecting
JavaScript to hide the automation, so there is no injected script for a page to find
and no redefined property to catch. The fingerprint (navigator, screen, WebGL, canvas,
fonts, audio, timezone, WebRTC) is generated as a coherent whole at launch, which is
the part that actually matters: a Windows user agent shipping Linux fonts is worse than
no spoofing at all. Set a proxy and timezone, locale and geolocation follow its exit IP
instead of contradicting it.

**🔑 Sign in once, when you need to.** Every tool takes a `profile` name, and each
profile is a persistent browser context on disk. For the sites that need an account,
open a visible window, sign in yourself with your password manager and your 2FA, and
every later conversation reuses that session. The agent never sees your credentials.
See [docs/profiles.md](docs/profiles.md).

**🚦 Conversations cannot collide.** `profile` is required on every call except
`list_sessions`, it has no default, and the profile is held under a cross-process lock.
2 conversations naming 2 profiles get 2 browsers, both persistent, in 1 server process.
A second conversation asking for a profile that is already held gets a typed
`ProfileInUseError` immediately, never a shared browser. That prevents the failure that
wastes an afternoon: one conversation navigating away while another is mid-form. See
[docs/isolation.md](docs/isolation.md).

**🪶 Tools that respect your context window.** `snapshot` walks the visible DOM with
ARIA-aware heuristics (roles, `aria-label`, `<label for>`, focusability) and stamps
`data-mcp-uid="eN"` on interactive elements, which every later tool addresses by uid.
Output is capped at 1500 nodes with an explicit truncation note. `click`, `fill` and
`navigate` take `observe`, which appends the resulting page state to the same call, so
1 round trip instead of 2. Both accept a CSS selector directly, skipping the snapshot
when you already know the element. Screenshots downscale on request and log their real
token cost. Errors are 1 line, not a 40-line Playwright stack trace. 30 tools in total.

**💻 Linux, Windows and macOS.** Including an opt-in shared daemon so several
conversations can use 1 browser process, over a Unix socket on POSIX and a
token-guarded loopback socket on Windows. See [docs/daemon.md](docs/daemon.md).

## 📊 How it compares

Verified by reading each project's source and issue tracker.

| | mcp-camoufox | playwright-mcp | chrome-devtools-mcp | agent-browser |
|---|---|---|---|---|
| **Anti-detect** | the browser build itself, on by default | 1 Chromium launch flag | none in the repo | none locally, forwarded to paid cloud providers |
| **Session identity** | a required `profile` argument on every call | derived from a hash of the working directory | 1 directory per Chrome channel | optional, defaults to `"default"` |
| **2 conversations at once** | 2 named profiles, both persistent, 1 process | `--isolated` per client, which gives up persistence | `--isolated` per client | same browser unless each names a session |
| **Persistent login** | yes, by name | yes | yes | opt-in |
| **GeoIP-coherent locale and timezone** | yes, from the proxy exit IP | no | no | no |
| **Humanised cursor** | optional, in the browser build | no | no | no |

Their maintainers describe the anti-detect gap themselves. chrome-devtools-mcp
[#553](https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/553), asking for
stealth, has been open since November. On playwright-mcp
[#58](https://github.com/microsoft/playwright-mcp/issues/58) the answer was "the web
site you are automating properly detected the bot". agent-browser
[#506](https://github.com/vercel-labs/agent-browser/issues/506), about Cloudflare, has
no maintainer reply. It is not an oversight on their part: bolting stealth onto Chrome
from JavaScript produces a detectable patch, which is why it has to be in the browser
build.

## 📚 Documentation

Full docs in [docs/](docs/). Start with
[getting-started.md](docs/getting-started.md), then
[tools.md](docs/tools.md) for the reference and
[configuration.md](docs/configuration.md) for every environment variable.

## 🙏 Credits

This project is a thin MCP server on top of other people's hard work.

[Camoufox](https://camoufox.com) is built and maintained by
[daijro](https://github.com/daijro), who patched Firefox at the engine level and keeps
it ahead of anti-bot systems. That is the difficult part, and it is theirs. Fingerprint
data comes from [BrowserForge](https://github.com/daijro/browserforge), the humanised
cursor from [HumanCursor](https://github.com/riflosnake/HumanCursor). Underneath,
Mozilla's Firefox and Microsoft's Playwright. The server is built on
[FastMCP](https://github.com/jlowin/fastmcp).

If the anti-detection is what brought you here, the thanks go upstream. Star
[Camoufox](https://github.com/daijro/camoufox).
