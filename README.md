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
  uvx --from git+https://github.com/agelyhq/mcp-camoufox mcp-camoufox
```

Or in any MCP client's config:

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/agelyhq/mcp-camoufox", "mcp-camoufox"],
      "env": { "CAMOUFOX_HEADLESS": "virtual" }
    }
  }
}
```

Once it is on PyPI that shortens to `uvx mcp-camoufox`, with no `--from`.

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/). The first tool call downloads the
Camoufox browser, which is a few hundred megabytes and takes a minute or two: it happens
inside that call, so the first request looks slow and later ones are fast. `virtual` runs a
real windowed browser inside Xvfb, invisible to you and harder to detect than headless; it
is Linux only, so use `true` on Windows and macOS.

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

**🫥 A uid that leaves no trace.** `snapshot` walks the visible DOM with ARIA-aware
heuristics (roles, `aria-label`, `<label for>`, computed accessible names) and hands every
interactive element an `eN` uid. That uid lives in a table inside the tab's own heap, never
in the page: no attribute is written, no listener is added, no global appears. A uid names
an **element**, not a position, so it survives a re-render and only navigation renumbers.
Clicking checks first that the element is really the one under the cursor, so a cookie
banner produces an error naming the banner instead of a success on the wrong thing.

**🪶 Tools that respect your context window.** Snapshots cap at 1500 nodes, `evaluate`
caps its own output, and both say what they truncated and how to see more. `click`, `fill`
and `navigate` take `observe`, which appends the resulting page state to the same call, so
1 round trip instead of 2. `find` locates an element by role, name or text without paying
for a full snapshot, and `get_element` reads one property without writing JavaScript. Both
`click` and `fill` also accept a selector directly: plain CSS, plus `:has-text("...")` and
`text=...`. Screenshots downscale on request and log their real token cost. Errors are 1
line, not a 40-line stack trace. 27 tools in total.

**💻 Linux, Windows and macOS.** Including an opt-in shared daemon so several
conversations can use 1 browser process, over a Unix socket on POSIX and a
token-guarded loopback socket on Windows. See [docs/daemon.md](docs/daemon.md).

## 📊 What makes it different

3 things, and they are all in the browser rather than bolted on above it.

**The anti-detection is the build.** Camoufox patches Firefox at the C++ level, so the
spoofing is not observable from JavaScript running in the page. Stealth added from
JavaScript is itself a detectable patch, which is the whole reason this project starts
from a different browser instead of a different script.

**This layer adds nothing on top.** Element identity lives in the tab's heap, not in the
DOM. No attribute is written, no listener is added, no global appears, and no automation
event is dispatched at any point. That is a contract, checked by
`tests/test_no_markers.py` on every uid-consuming path, and its exact limit is written
down in [docs/anti-bot.md](docs/anti-bot.md) rather than glossed over.

**Isolation is mandatory, not a flag.** Every call names a `profile`. 2 names never
share state, the same name is exclusive across OS processes, and both profiles stay
persistent, so 2 conversations can work at once without either giving up its logins. The
locale and timezone follow the proxy exit IP, so the browser's story about where it is
holds together.

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
