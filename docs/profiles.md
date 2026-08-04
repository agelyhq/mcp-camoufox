# 🔑 Profiles: sign in once, reuse forever

Every tool takes a `profile` name. That name is the whole session model: it selects a
browser, and its state on disk.

```
navigate(profile="gcp", url="https://console.cloud.google.com")
```

The first call for a name launches a browser with a persistent context rooted at
`<data_dir>/profiles/gcp/`. Cookies, localStorage, IndexedDB and service workers all
survive `close_session` and process restarts. The next conversation that uses `gcp`
picks up exactly where the last one left off, already signed in.

Names are yours to choose. One per site, one per client, one per identity, whatever
matches how you work.

## ✍️ Signing in by hand

This is the pattern that makes hard sites tractable, and it is worth doing explicitly
the first time:

1. Start the session with a visible window, so you can interact with it.

   ```
   navigate(profile="gcp", url="https://console.cloud.google.com", headless=false)
   ```

2. Sign in yourself, in that window. Password manager, 2FA, hardware key, whatever the
   site demands. The agent is not involved and never sees your credentials.

3. Tell the agent to carry on. From here it drives the same authenticated session.

4. Later conversations reuse it:

   ```
   navigate(profile="gcp", url="https://console.cloud.google.com/iam-admin")
   ```

   No sign-in step. The session is already there.

Two things make this work better here than elsewhere. The window is a real Firefox
that the site does not flag as automated, so the sign-in actually completes (see
[anti-bot.md](anti-bot.md)). And the profile name is explicit, so the agent cannot
quietly land in the wrong browser state.

## 🗄️ What is stored, and what that means

A profile directory contains live session cookies for every site you signed into with
it. Anyone who can read that directory can act as you on those sites.

- Directories are created owner-only.
- They are never synced anywhere. There is no cloud sync and none is planned, because
  syncing live sessions is a decision that belongs to you and your own tools.
- `close_session` closes the browser and keeps the directory. To actually sign out,
  delete `<data_dir>/profiles/<name>/`.

If you use the shared daemon, the same rules apply, plus the daemon's control channel
holds access to all of them at once. See [daemon.md](daemon.md).

## 💡 Useful patterns

**One profile per site.** `gcp`, `linkedin`, `bank`. Sessions stay independent, and a
site that breaks does not take the others down.

**A throwaway profile for tests.** Any unused name creates a clean browser. Delete the
directory when done.

**A profile per client or per identity.** Two Google accounts, two profiles, no
signing out and back in.

**Check what is live** with `list_sessions`, which lists active profiles, their tab
count, and each tab's URL and title.

## ⚠️ Limits

A profile is exclusive across the whole machine, not just within one conversation. If
another process holds it, you get:

```
Error: ProfileInUseError: profile 'gcp' is locked by another process
```

That is intentional. Two agents in one browser corrupt each other's work in ways that
are hard to debug. Use a different name, or wait. See [isolation.md](isolation.md).

Sessions never expire on their own. They close when you call `close_session` or when
the process exits. Nothing evicts a session on a timer.
