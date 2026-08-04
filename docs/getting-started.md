# 🚀 Getting started

This walks through a first real session, the kind that fails with a Chrome-based
server: signing in somewhere and then letting the agent work.

If you have not installed it yet, see the [README](../README.md).

## ✅ Check it runs

Ask your agent for something harmless:

```
Open example.com with the profile "scratch" and tell me the page title.
```

The first call takes a while: it downloads the Camoufox browser if it is not there
yet, then launches it. Later calls are fast.

Behind that, the agent calls `navigate(profile="scratch", url="https://example.com")`
and then `snapshot(profile="scratch")`. The profile name is the only thing you have to
decide.

## 🔐 Sign in somewhere hard

Take the GCP console, which will not let an automated Chrome sign in.

**1. Open it in a real window.**

```
Open the GCP console with the profile "gcp", in a visible window,
and wait for me.
```

The agent calls `navigate(profile="gcp", url="https://console.cloud.google.com",
headless=false)`. A Firefox window appears.

**2. Sign in yourself.** Password, 2FA, hardware key, whatever it asks for. The agent
is not involved and never sees any of it.

**3. Hand it back.**

```
I'm signed in. Take a snapshot and list the projects.
```

**4. Come back tomorrow.** In a new conversation:

```
In the "gcp" profile, go to the IAM page and list the service accounts.
```

No sign-in step. The session is on disk and still valid. That is the entire point of
[profiles](profiles.md).

## ✈️ A non-engineering example

The same pattern works for the sites people actually spend time on. Booking,
Tripadvisor and Airbnb all block automated browsers, and all three are places where an
agent doing the boring parts is genuinely useful:

```
With the profile "travel", open Booking, search for a hotel in Lisbon
for the 12th to the 15th, filter to 8+ rated places with free
cancellation, and give me the five cheapest with their addresses.
```

Sign in once in that profile if you want it to see your saved lists and prices, and
every later trip planning conversation reuses it.

## 🪶 Working efficiently

A few habits make a large difference to how fast and how cheaply this runs.

**Snapshot, do not screenshot.** `snapshot` returns the page structure as text with
uids. It answers "what is on this page and what can I click" for a fraction of the cost
of an image. Reach for `screenshot` when the question is genuinely visual.

**Use `observe` instead of a second call.** `click(..., observe="snapshot")` returns
the confirmation and the new page state in one round trip.

**Use a selector when you know one.** `fill(profile="x", selector="#email",
value="...")` skips the snapshot entirely.

**Keep the window small.** `CAMOUFOX_VIEWPORT=1000x700` cuts image cost directly,
since screenshots are billed by pixel count.

**Use `virtual` on Linux.** `CAMOUFOX_HEADLESS=virtual` gives you a real windowed
browser inside Xvfb: invisible to you, harder to detect than headless.

## 🩹 When something goes wrong

**A uid does not work.** The page changed. Take a new snapshot. Navigation invalidates
uids by design.

**`ProfileInUseError`.** Another conversation or process holds that profile. Use a
different name, or close the other one. See [isolation.md](isolation.md).

**A site still blocks you.** Work through the checklist in
[anti-bot.md](anti-bot.md), starting with the cheapest check: does the same site work
in a normal browser from the same machine and IP?

**Something else.** The telemetry log has the exact arguments, the URL and the error
for every call: `<data_dir>/logs/<profile>.jsonl`. See [telemetry.md](telemetry.md).

## 👉 Next

- [tools.md](tools.md), the full tool reference
- [configuration.md](configuration.md), every environment variable
- [isolation.md](isolation.md), running several conversations at once
- [daemon.md](daemon.md), sharing one browser process between them
