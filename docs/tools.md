# 🧰 Tool reference

Every tool takes `profile` as its first argument. It names the browser session, and
the first call for a given name launches a dedicated browser with a persistent on-disk
context. `list_sessions` is the only tool without it.

Every tool returns a plain string. On failure it returns a single line,
`Error: <Type>: <message>`, or `Timeout: <message>` for a timeout. `screenshot` is the
only tool that returns an image.

## 🔁 The loop

Most work looks like this:

1. `navigate` to a page. The session starts on the first call.
2. `snapshot` to get the page structure with `eN` uids on interactive elements.
3. Act with `click`, `fill`, `type_text` and friends, addressing elements by uid.
4. Re-snapshot when the page changes. Navigation invalidates uids.

Steps 3 and 4 collapse into one call with `observe`, which appends the new page state
to the action's result. That is one round trip instead of two.

## 🗂️ Session

| Tool | Key parameters | What it does |
|---|---|---|
| `list_sessions` | none | Lists active profiles with page count, and the URL and title of each tab. |
| `close_session` | `profile` | Closes the browser. The on-disk profile is kept for next time. |

## 🧭 Navigation

| Tool | Key parameters | What it does |
|---|---|---|
| `navigate` | `profile, url, [fingerprint_os, viewport_width, viewport_height, locale, block_images, block_webrtc, headless], observe?, timeout?` | Loads a URL, creating the session on the first call. The bracketed options apply only when the session is created, and are ignored with a note on an already-running profile. |
| `reload` | `profile` | Reloads the current page. |
| `go_back` | `profile` | Back in history. |
| `go_forward` | `profile` | Forward in history. |
| `wait_for` | `profile, condition, selector?, expression?, return_expression?, timeout?` | Waits for `load`, a CSS `selector`, `network_idle`, or a `predicate` (a JS `expression` re-evaluated each frame). `return_expression` runs once after a successful wait and its value is appended. |

## 📑 Tabs

| Tool | Key parameters | What it does |
|---|---|---|
| `list_pages` | `profile` | Lists open tabs with index, title, url and which one is active. |
| `new_page` | `profile, url?` | Opens a tab, optionally navigating it. It becomes active. |
| `close_page` | `profile, page_idx` | Closes a tab by index. |
| `select_page` | `profile, page_idx` | Makes a tab active. |

## 🔍 Inspection

| Tool | Key parameters | What it does |
|---|---|---|
| `snapshot` | `profile, max_nodes?, interactive_only?` | The visible DOM as text, walked with ARIA-aware heuristics, with `eN` uids stamped on interactive elements. This is the main way to see a page. `max_nodes` defaults to 1500 and truncates with a note; `interactive_only` drops structural leaves. |
| `screenshot` | `profile, full_page?, uid?, max_width?` | A PNG of the viewport, the full page, or one element's bounding box. `max_width` downscales and returns the coordinate multiplier alongside the image, which `click_at` needs. |
| `get_html` | `profile, selector?, max_chars?, strip_scripts?, mode?` | Post-JavaScript markup or text. `selector` scopes to the first match. `mode='html'` (default, scripts stripped) or `'text'` for `innerText`. Capped at `max_chars`, default 20000, `<=0` for unlimited. |

Screenshots are the most expensive thing you can ask for. A snapshot usually answers
the same question for a fraction of the tokens. Keep the viewport small
(`CAMOUFOX_VIEWPORT=1000x700` is a good default for local development) because image
cost scales with pixel count.

## 🖱️ Interaction

| Tool | Key parameters | What it does |
|---|---|---|
| `click` | `profile, uid \| selector, double_click?, observe?` | Clicks an element. Pass exactly one of `uid` or a CSS `selector`. |
| `click_at` | `profile, (x, y) \| points, double_click?, observe?` | Clicks raw viewport coordinates, for canvases and anything without a uid. `points: [[x,y], ...]` clicks a batch in order. |
| `hover` | `profile, uid` | Hovers an element. |
| `drag` | `profile, from_uid, to_uid` | Drags one element onto another. |
| `fill` | `profile, uid \| selector, value, clear_first?, observe?` | Sets a field's value. On a `<select>` it picks the option matching by value, then by visible label. |
| `fill_form` | `profile, fields` | Fills several fields at once: `fields = [{uid, value}, ...]`. |
| `type_text` | `profile, text, submit?` | Types into whatever has focus, optionally pressing Enter afterwards. |
| `press_key` | `profile, key` | Sends a key, for example `Enter` or `Control+A`. |
| `scroll` | `profile, direction, amount?, uid?` | Scrolls the page, or scrolls an element into view. |
| `upload_file` | `profile, uid, file_path` | Sets a file input's value. |
| `handle_dialog` | `profile, action, prompt_text?` | Accepts or dismisses a pending `alert`, `confirm` or `prompt`. |

### uid or selector

`click` and `fill` accept exactly one of the two. Passing both, or neither, is an
error rather than a silent preference.

Use a uid when you found the element in a snapshot. Use a selector when you already
know it (`selector="#email"`), which skips the snapshot entirely and is much cheaper.
The selector path is Playwright-native and acts on the first match.

### observe

`click`, `click_at`, `fill` and `navigate` accept `observe`:

- `none` (default): just the confirmation.
- `snapshot`: a fresh uid tree is appended. This also refreshes uids, exactly as if you
  had called `snapshot`.
- `text`: the page body's `innerText`, capped at 4000 characters.

There is deliberately no `screenshot` mode, because `screenshot` is the only tool
allowed to return an image.

## 📜 Scripting

| Tool | Key parameters | What it does |
|---|---|---|
| `evaluate` | `profile, script` | Runs JavaScript in the page and returns the JSON-serialised result. |

## 🌐 Network

| Tool | Key parameters | What it does |
|---|---|---|
| `list_network_requests` | `profile, resource_types?, page_size?, page_idx?, include_preserved?` | Paginated request and response log for the active tab. |
| `get_network_request` | `profile, reqid, include_body?, max_body_size?` | Full headers and body for one request. |

## 🖥️ Console

| Tool | Key parameters | What it does |
|---|---|---|
| `list_console_messages` | `profile, levels?, limit?, include_preserved?` | Recent console messages, optionally filtered by level. |

## ⚡ Performance

| Tool | Key parameters | What it does |
|---|---|---|
| `performance_summary` | `profile` | Navigation and Resource Timing summary: DNS, connect, TTFB, DOMContentLoaded, load, resource count, transfer size, and a breakdown by initiator type. |

This is the standard W3C timing data, read from the page. It is not a Chrome
performance trace and there is no Lighthouse audit here. See
[decisions.md](decisions.md) for why those are out of scope rather than missing.

## ⚠️ Errors

Errors are one line, always. The Playwright "Call log:" tail is stripped and newlines
are folded, because a forty-line stack trace in an agent's context is forty lines of
noise.

Common ones:

| Message | Meaning |
|---|---|
| `Error: ValueError: unknown or stale uid 'e12'; take a new snapshot` | The page changed since the snapshot. Take a new one. |
| `Error: ProfileInUseError: profile 'work' is locked by another process` | Another conversation holds that profile. Use a different name. See [isolation.md](isolation.md). |
| `Error: ValueError: provide exactly one of uid or selector` | You passed both or neither. |
| `Timeout: ...` | The operation exceeded its timeout. |
