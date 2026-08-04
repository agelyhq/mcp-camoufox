# 🛡️ Why sites stop blocking the browser

This page explains what actually happens, so you can predict when it will work and
when it will not. If you want the short version: the browser is patched at the C++
level rather than at the JavaScript level, which is why the usual detection checks
come back clean.

## ❌ What normal automation gets wrong

A page can tell it is being automated in 3 broad ways.

**The automation flag.** Chrome and Firefox both expose `navigator.webdriver` when
driven by a test framework. Stealth plugins delete or redefine it from JavaScript, but
the redefinition is itself detectable: a property that should be a native getter comes
back as a plain value, `Function.prototype.toString` no longer returns `[native code]`,
and the same check run inside a Web Worker sees the original value because the patch
only ran in the main world.

**The injected agent.** Playwright and Puppeteer inject a script into every page to do
their work. That script lives in the same JavaScript environment as the site, so the
site can see it.

**Fingerprint incoherence.** A headless browser tends to report a screen the size of
its viewport, no fonts, a software WebGL renderer, a timezone that does not match its
IP, and a user agent that contradicts its own `navigator.platform`. Any single one of
those is a signal. Together they are conclusive.

## ✅ What Camoufox does instead

[Camoufox](https://camoufox.com) is a Firefox fork, driven over a patched Juggler
protocol (Firefox's own automation protocol, not CDP).

**The automation agent is sandboxed.** Camoufox patches Juggler so the automation code
gets its own isolated copy of the page. From the Camoufox documentation: "websites can
no longer see any JavaScript that Playwright would typically inject". The real page is
untouched, and input events go through Firefox's original user input handlers rather
than through synthetic JavaScript events.

**The fingerprint is set below JavaScript.** Values are injected through a config that
is, again quoting the documentation, "intercepted at the C++ implementation level,
making the changes undetectable through JavaScript inspection". So
`Object.getOwnPropertyDescriptor` returns what it should, `toString` returns
`[native code]`, and a check run inside a worker agrees with the same check run in the
main window. There is nothing to catch, because nothing was redefined at runtime.

**The fingerprint is coherent by construction.** Camoufox generates a complete,
internally consistent profile rather than patching individual values: navigator and
hardware properties, screen and window geometry, WebGL vendor and renderer with
matching shader precision, canvas output (jittered at the rasterizer level, not with
JavaScript noise), AudioContext characteristics, an OS-appropriate font set with
randomised letter spacing, timezone and locale, WebRTC candidate IPs, speech voices,
battery, and HTTP headers that match the declared navigator.

That coherence is the part that matters. Spoofing a Windows user agent while shipping
Linux fonts and a Mesa WebGL renderer is worse than not spoofing anything.

## 🚫 What it does not do

Being honest here saves you hours of debugging the wrong thing.

**It does not solve CAPTCHAs.** No CAPTCHA solving is attempted, ever. If a site
presents a challenge that requires human input, you get to solve it by hand in the
visible window. That is usually fine: with a persistent profile you do it once.

**It does not fix your IP.** Bot detection weighs IP reputation heavily, and a
datacenter IP is a strong signal regardless of how good the fingerprint is. Camoufox is
designed to be used with residential proxies. If a site blocks you from a cloud VM,
try the same site from your laptop before blaming the fingerprint.

**It does not defeat behavioural analysis.** Detection systems also watch how you move,
type and scroll. From the Camoufox README: "Anti-bot systems also run client-side
scripts to monitor your behavior. This isn't perfect. It may still be detected." A
humanised cursor exists (see `CAMOUFOX_HUMANIZE` in
[configuration.md](configuration.md)) but it is best effort, and it is off by default
for reasons documented in [decisions.md](decisions.md).

**It does not change the TLS handshake.** Firefox's TLS stack is used unmodified, so
JA3 and similar transport-level fingerprints identify it as Firefox. That is fine
because it identifies it as a *real* Firefox, but it means you cannot pretend to be
Chrome at the network level.

**It cannot impersonate Chrome.** SpiderMonkey and V8 differ in ways that JavaScript
can observe, so a Chromium fingerprint is not something Camoufox tries to fake. A site
that hard requires Chrome will not work here.

**It does not protect your account.** Sites also score behaviour at the account level:
volume, timing, and what you actually do. Passing the browser check is not permission
to hammer an API through the UI.

## 🎯 What this means in practice

**Prefer a visible window over headless.** Headless modes carry additional tells even
in Camoufox. On Linux, `CAMOUFOX_HEADLESS=virtual` runs the browser inside an Xvfb
display: invisible to you, but a real windowed browser as far as the page is concerned.
That is the best combination of the 2 and it is what the E2E suite runs. On Windows
and macOS, where Xvfb does not exist, `true` is the fallback.

**Sign in by hand, once.** The most reliable pattern is a visible window, a human
sign-in including any 2FA, then a persistent profile for everything after. See
[profiles.md](profiles.md). This also means the agent never handles your credentials.

**Use a residential proxy for hostile targets.** `CAMOUFOX_PROXY` takes a full proxy
URL and turns on GeoIP, so timezone, locale and geolocation are derived from the proxy
exit IP instead of contradicting it.

## 🔎 Checking it yourself

Point the browser at a fingerprint test page and read the result, rather than trusting
this document:

- [CreepJS](https://abrahamjuliot.github.io/creepjs/), the most thorough of the 3
- [BrowserLeaks](https://browserleaks.com/)
- [BrowserScan](https://www.browserscan.net/)

```
navigate(profile="fingerprint-test", url="https://abrahamjuliot.github.io/creepjs/")
screenshot(profile="fingerprint-test", full_page=true)
```

## 🩹 When a site still blocks you

Work through it in this order, because the cheapest checks eliminate the most cases:

1. Open the same site in a normal browser, on the same machine and the same
   connection. If it also fails there, the problem is your IP, not the browser.
2. Switch from `headless=true` to a visible or `virtual` window.
3. Sign in by hand in the visible window, then let the agent reuse the profile.
4. Try a residential proxy.
5. Check whether the site is one of those that genuinely require Chrome.

If none of that works, open a [blocked site
report](https://github.com/agelyhq/mcp-camoufox/issues/new?template=blocked_site.yml).
The template asks for the things needed to tell a fingerprint problem apart from an IP
problem. Fingerprint gaps get reported upstream to Camoufox, where they belong.

## 🙏 Credit where it is due

None of this is our work. Camoufox is built and maintained by
[daijro](https://github.com/daijro), on top of Firefox, with fingerprint data from
[BrowserForge](https://github.com/daijro/browserforge) and a humanised cursor ported
from [HumanCursor](https://github.com/riflosnake/HumanCursor). This project is a thin
MCP server on top. If the anti-detection is what you are here for, the thanks go
upstream.
