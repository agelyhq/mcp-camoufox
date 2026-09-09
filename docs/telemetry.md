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
| `args` | Arguments: each string capped at 10,000 characters, file bytes elided as `<N bytes>`, a secret field's value replaced (see below). |
| `duration_ms` | Wall-clock duration. |
| `ok` / `error` | `false` plus a one-line `<Type>: <message>` on failure, else `true` and `null`. |
| `result` | Human-readable outcome, capped at 10,000 characters. |
| `result_chars` | Length of that outcome before truncation. Absent when there was no text at all. |
| `url` | Best-effort active page URL at call time. Never creates a session. |

Anything cut carries a `...[N chars]` suffix naming its true length, and `result_chars`
is the length of the note it describes, measured before anything was cut. It is absent
(`null`) exactly when the call produced no text: a bare image — `screenshot` without the
downscale note — and a call cancelled before it returned. The 2 ceilings are separate
constants (`MAX_ARG_CHARS`, `MAX_RESULT_CHARS` in `telemetry.py`) because they answer different
questions. Both are 10,000, measured rather than guessed: the longest argument ever
recorded here is 6,375 characters and the 99th percentile is 906, while results run to a
median of 84, a 99th percentile of 7,743 and a single 353,120-character snapshot. There
is no rotation, so the file only grows; the whole history of one heavy user with nothing
truncated measured 2.2 MB.

On `screenshot` records: `img_w`, `img_h`, `img_bytes` and `est_image_tokens`
(`min(ceil(w*h/750), 1568)`), so image spend is measurable rather than guessed.

On `evaluate` records: `intent` (a coarse bucket, one of `click`, `state`, `style`,
`wait`, `read`, `other`), `script_hash` (a fingerprint of the script with literals
stripped, so the same query with different arguments hashes the same) and `script_len`.

On `click`, `fill` and `fill_form` records: `targets`, one object per element the call
**addressed**, in the order it addressed them — not one per element it found. The
address is noted before any page work, so a stale uid and a selector that matched
nothing each still produce an entry: what was attempted is exactly what a log is read
for, and it is also what the redaction rule below is keyed on.

Each carries what is known and omits what is not: `uid`, `selector` (when that was the
address), `tag`, `role`, `input_type`, `label` (the first of the element's aria-label,
bound `<label>`, placeholder and form name that answers) and `text` (its own text).
`resolved` is always there and says outright whether the address found an element: an
entry with `"resolved": false` carries nothing but that address and possibly the
`secret` flag a selector alone can raise. A uid names nothing in a later
document, so this is what makes a log readable after the page has moved on. Every string
in that object is capped like an argument: it is flattened onto the line without passing
through the argument truncation, and the selector a caller sent and a custom element's
`tag` are each as long as whoever wrote them cares to make them. The names the page
writes — `label`, `text` and the `role` attribute — arrive capped at 80 characters by
the walk itself, so nothing 65,000 characters long has to cross the protocol first.

Every field is taken from the measurement the action already makes, so recording them
costs no extra page call. The full accessible-name computation is deliberately not run:
it collects the text of the whole subtree, and this measurement is re-probed until the
element settles, so it would be paid per poll iteration on the hottest path in the
product. One walk is kept — the text of the bound `<label>`, which is the only visible
name most form fields have, is read from that label's own subtree and skipped outright
for an element that has none.

```json
{"tool": "click", "args": {"selector": "#save"}, "result": "Clicked <button> at (412, 233)",
 "targets": [{"uid": "e42", "selector": "#save", "tag": "button", "role": "button",
              "text": "Save changes", "resolved": true}]}
```

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

## 🔐 What is redacted, and what is deliberately not

A value typed into a field that looks like a secret is replaced by
`<redacted N chars>`, which keeps its length and drops its content. The target is still
recorded and marked `"secret": true`, minus its own `text` — a `contenteditable` holds
what was typed into it — so the log still says which field was filled, just not with
what.

A field looks like a secret when the page declares it one (`<input type="password">`),
or when **any** of the names it carries — its aria-label, its bound `<label>`, its
placeholder, its form name — or the selector that addressed it matches one of a short
closed list of whole words, English and French: `password`, `passwords`, `passwd`,
`pwd`, `passphrase`, `passe`, `motdepasse`, `secret`, `secrets`, `token`, `jeton`,
`apikey`, `otp`, `totp`, `cvv`, `cvc`. A name's words are also tested joined, so "Mot de
passe" is `motdepasse` and "API Key" is `apikey`. All 4 names are tested, not just the
one recorded as `label`: with `<label for="cvc">Security code</label>`, the label is what
a reader wants to see and the form name is the only part that says "card verification
code". The list is in `tools/_secrets.py`, which argues each word.

A value is also redacted when the call resolved **nothing** — a stale uid, a selector
that matched nothing. That fill reached no page, so its value is worth nothing to
anything generated from this log, while a re-typed password on a uid a navigation
invalidated is the most common retry there is.

Everything else is logged in full, on purpose. Search terms, filters, dates and
identifiers are the substance of what an agent did, and a log that hides them answers
nothing — `code` is not on the list above for exactly that reason, and neither is bare
`key` or bare `pin` ("PIN Code" is the Indian postal code, and it is on every shipping
form; "Code promo" and "PIN Code" are both logged in full).

That said, a word list cannot tell a credential from a search term by name alone, and
these are the residual false positives, named rather than hidden: a crypto explorer's
"Search by token name", a "Secret Santa" wish field, a "Passe Navigo" transit lookup, and
any filter called "API Key", which the joined form catches. Each is recorded as
`<redacted N chars>`. They are accepted because the opposite mistake is permanent: `passe`
in particular stays because "Confirmez votre mot de passe" is a real password field that
nothing else on the list catches.

4 limits worth knowing:

- Redaction rewrites `args` only. `result` and `error` are written as the tool produced
  them, which is why a fill a `<select>` or a checkbox refuses names the length of what
  it was given (`<N chars>`) instead of quoting it. The value of an `<input
  type="password">` is therefore elided at every renderer that can reach it — `snapshot`,
  `find`, the observation a fill appends, and `get_element(prop="value")` — as
  `<redacted N chars>`. Other field content can still surface: a `<select>` echoes into
  the result line the option it picked, spelled as the PAGE spells it, never as the
  argument did and never past 80 characters; and `snapshot` renders a `value=` part for
  any non-password input that already has one.
- The word list is matched against names and selectors, never against the value itself: a
  password typed into a field called "Search" is logged.
- Dropping a secret target's own `text` covers the `targets` object and nothing else. A
  `contenteditable` holds what was typed into it, and a fill called with
  `observe="snapshot"` or `observe="text"` appends the page's own rendering to the same
  record's `result`: the walk elides the value of an `<input type="password">`, which has
  no text node, but a rich field renders its text like any other element. A secret typed
  into a `contenteditable` is therefore in the record whenever that fill was asked to
  observe. It is named here rather than fixed at the walk, for the reason the numeric
  `{"otp": 123456}` and the multipart body below are: eliding an element's text on
  suspicion would gut the observation an agent asked for.
- Nothing leaves the machine either way, but read a log before pasting it into an issue.

Records also contain URLs, which can carry tokens in a query string.

## 🍪 Credentials in a captured request

`get_network_request` renders one captured request as the browser saw it, and that is
where a signed-in profile's credentials live: the `Cookie` header of a profile whose
login was established by hand IS that login, and a sign-in POST body carries the very
password the rule above takes out of `args`. Both are elided at the **renderer**, like
the password value in the snapshot walk and for the same reason — the tool result is
handed to the model and is also the record's `result`, which redaction never rewrites.

- **Authentication headers.** `Cookie`, `Set-Cookie`, `Authorization` and
  `Proxy-Authorization` keep their name and lose their value, which becomes
  `<redacted N chars>`. Names are matched without regard to case, because HTTP header
  names are case-insensitive and Firefox hands most of them over lowercased. The set is
  in `tools/_net_secrets.py`, which argues each entry.
- **The request body.** One field at a time, judged by its name against the same closed
  word list a typed value is judged by, and substituted in place: `password=hunter2`
  becomes `password=<redacted 7 chars>` and every other byte of the payload is rendered
  exactly as captured. Gutting or truncating the body was rejected outright — inspecting
  an API payload is what this tool is for, and the field that explains a 400 is as likely
  to be the last one as the first.

What that deliberately leaves open, named rather than hidden:

- Only `application/x-www-form-urlencoded` and `*/json` bodies are inspected. A
  multipart form post, a plain-text or GraphQL body, protobuf, any other declared type,
  and a request that declares **no** `Content-Type` at all are rendered verbatim: a body
  that cannot be parsed with confidence is left alone rather than mangled by a guess, and
  an absent type says no more about how to read one than an unknown type does.
- A credential under a name the word list does not carry (`auth`, `pass`, `signature`,
  `session`) is rendered in full, exactly as a fill into a field with that name would be
  logged in full. Only quoted JSON strings are matched, so a numeric `{"otp": 123456}`
  survives too.
- The **response** body is not inspected at all, so a sign-in answering
  `{"access_token": "..."}` renders it whole. That is a decision, not an oversight:
  reading a value out of a response — a CSRF token to post back, an id to follow — is
  the main reason an agent calls this tool, and eliding it would break the tool for the
  case it exists for. `include_body=false` turns the body off per call.
- The URL is rendered as captured, so a token in a query string or a credential in the
  userinfo part of a URL is in the record, as it already is in the `url` field of every
  other record.
