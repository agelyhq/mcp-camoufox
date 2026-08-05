# 📊 Telemetry and logs

Every tool call appends one JSON object to a per-profile log file. It is local, it is
never sent anywhere, and it exists so you can answer "what did the agent actually do,
and what did it cost".

```
<data_dir>/logs/<profile>.jsonl    one line per tool call
<data_dir>/logs/_server.jsonl      lifecycle records, and tools without a profile
```

See [configuration.md](configuration.md) for where `<data_dir>` is on your platform.

## 🧾 A record

```json
{"ts": "2026-07-15T12:00:00.000Z", "profile": "alice", "tool": "click",
 "args": {"uid": "e3"}, "duration_ms": 42.7, "ok": true, "error": null,
 "result": "Clicked e3", "result_chars": 10, "url": "https://example.com/form"}
```

| Field | Meaning |
|---|---|
| `ts` | ISO-8601 UTC timestamp. |
| `profile` | Which session. |
| `tool` | Tool name. |
| `args` | Arguments, truncated: long strings capped, file bytes elided. |
| `duration_ms` | Wall-clock duration. |
| `ok` / `error` | `false` plus a one-line `<Type>: <message>` on failure, else `true` and `null`. |
| `result` | Short human-readable outcome, capped at 200 characters. |
| `result_chars` | Full length of the result before truncation. |
| `url` | Best-effort active page URL at call time. Never creates a session. |

On `screenshot` records: `img_w`, `img_h`, `img_bytes` and `est_image_tokens`
(`min(ceil(w*h/750), 1568)`), so image spend is measurable rather than guessed.

On `evaluate` records: `intent` (a coarse bucket, one of `click`, `state`, `style`,
`wait`, `read`, `other`), `script_hash` (a fingerprint of the script with literals
stripped, so the same query with different arguments hashes the same) and `script_len`.

2 lifecycle markers also land in `_server.jsonl`: a `server_start` record with a
config snapshot (proxy redacted to scheme and host), and a `session_closed` record per
profile, written both when a session is closed explicitly and when the server exits
cleanly.

One limit worth knowing before you count on it: a server killed by a signal writes
nothing. An MCP client normally ends a session by closing the pipe, which is a clean exit
and does produce the marker, but a `kill` does not, and installing a signal handler to fake
one would collide with the daemon, which raises that same signal on purpose to trigger its
own graceful shutdown.

## 🎯 What it is for

**Cost.** Screenshots dominate token spend in browser automation. The image fields let
you total real image tokens per session and see whether a smaller viewport would pay
for itself.

```bash
jq -s 'map(select(.est_image_tokens)) | map(.est_image_tokens) | add' \
  ~/.local/share/camoufox-mcp/logs/work.jsonl
```

**Debugging.** When something failed 3 steps ago, the log has the exact arguments,
the URL at the time, and the one-line error. This is what the bug report template asks
for.

```bash
jq 'select(.ok == false)' ~/.local/share/camoufox-mcp/logs/work.jsonl
```

**Tool usage.** Which tools an agent actually reaches for, and which have never been
called once.

```bash
jq -r .tool ~/.local/share/camoufox-mcp/logs/work.jsonl | sort | uniq -c | sort -rn
```

That last one is what retired 5 tools in 0.3.0, and what added 2 others: the measurement
had to exist before the decision. It also found the most frequent error in the product,
which turned out to be a binary request body 9 tools away from where it surfaced. See
[decisions.md](decisions.md).

## 📝 Notes

Logging is best-effort. A logging failure never breaks a tool call.

It is fully automatic through the `@tool` decorator. If you are adding a tool, do not
log anything by hand.

Records contain URLs and truncated arguments, which can include what was typed into a
form. Nothing leaves the machine, but redact before pasting a log into an issue.
