# 🚦 Running several conversations at once

Open 2 Claude Code conversations, give them both browser work, and one of two things
usually happens: they fight over the same browser, or the second one fails to start.
Here, neither does, because the `profile` argument is mandatory and the lock behind it
is enforced across processes.

## ⚙️ How it works

`profile` is not optional and has no default. Every tool call names the session it
acts on, so an agent cannot end up in "the" browser by accident, only in the one it
asked for.

Behind the name, `SessionManager` takes a `filelock` on the profile directory before
launching. The lock is held by the OS process, so it works between 2 MCP servers,
between 2 conversations, and between a conversation and a stray terminal. When a
second process asks for a profile that is already held, it gets a typed error rather
than a corrupted session:

```
Error: ProfileInUseError: profile 'work' is locked by another process
```

Different names never share anything: separate browser process, separate context,
separate cookie jar, separate disk directory.

## 🎯 What this buys you in practice

The failure modes it prevents are the ones that waste an afternoon:

- Conversation B navigates away while conversation A is mid-form, and A's next click
  lands on a page that no longer exists.
- 2 agents call "select tab" in the same browser, and each acts on the other's tab.
- One conversation signs out, and the other silently loses its session.
- One conversation's snapshot returns the other conversation's DOM.

These are not hypothetical. They are documented in the issue trackers of the
Chrome-based MCP servers: chrome-devtools-mcp
[#1245](https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/1245) describes
agents operating on each other's tabs because "select page then act" is not atomic,
and playwright-mcp
[#1631](https://github.com/microsoft/playwright-mcp/issues/1631) documents snapshots
leaking DOM across clients on a shared context, which its maintainer confirmed cannot
be fixed by default without breaking existing clients.

The point is not that those projects are careless. It is that isolation has to be the
default, not a flag, because the flag is exactly what an agent forgets to pass.

## 🔗 When you want sharing instead

Sometimes you do want 2 conversations in 1 browser, typically to hand work from
one to the other. Use the same profile name from both, one at a time, or turn on the
shared daemon, which lets several conversations use one set of sessions through a
single process. See [daemon.md](daemon.md).

Isolation is unchanged in daemon mode: it is still keyed by profile name. The daemon
shares the process, not the profiles.

## 📊 Comparison

Most browser MCP servers persist profiles, so that is not the difference. The
difference is who chooses the session, and what happens when 2 agents want the same
one.

| | mcp-camoufox | playwright-mcp | chrome-devtools-mcp |
|---|---|---|---|
| Session selected by | a required `profile` argument, per tool call | the working directory (hashed into the profile path) | a global flag on the server process |
| Two conversations, same session | second one gets `ProfileInUseError` | conflict; their guard is a read-only probe of Chromium's own lock file, inert on Firefox and WebKit | share one browser, with documented races |
| Two conversations, different sessions | pass different names, both stay persistent | `--isolated` or a distinct `--user-data-dir` per client | `--isolated` per client |
| Persistence when running in parallel | kept | `--isolated` is mutually exclusive with a user data dir, so it is given up | given up with `--isolated` |
| Enforced or by discipline | enforced, no way to opt out | choosing distinct dirs is your job | your job |

To be even-handed: 2 of our conversations naming the **same** profile collide too.
The difference is what the fix costs. Ours is "pick another name", and you keep the
profile. Theirs is a flag chosen when the process starts, and on the parallel path it
costs you the persistent profile.
