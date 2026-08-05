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
3. Act with `click`, `fill`, `scroll` and friends, addressing elements by uid.
4. Re-snapshot when the page changes to see what is new. A snapshot no longer invalidates
   uids: an element still present keeps the uid it already had, and only navigation
   renumbers.

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
| `wait_for` | `profile, condition, selector?, expression?, return_expression?, timeout?, max_chars?` | Waits for `load`, a `selector`, `network_idle`, or a `predicate` (a JS `expression` polled every 50 ms). On expiry the error reports the last value the expression returned. `return_expression` runs once after a successful wait and its value is appended. |

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
| `snapshot` | `profile, max_nodes?, interactive_only?` | The visible DOM as text, walked with ARIA-aware heuristics, with an `eN` uid on every interactive element and a computed accessible name. This is the main way to see a page. `interactive_only` defaults to true; pass false for the full tree. `max_nodes` defaults to 1500 and truncates with a note. Nothing is written to the page. |
| `find` | `profile, role?, name?, text?, label?, placeholder?, test_id?, css?, exact?, limit?` | Locates a few elements without capturing the whole tree, and mints uids `click`, `fill` and `get_element` accept straight away. Read-only: it never activates anything. When nothing matches it reports what it did see, naming up to 5 candidates, so a typo is fixable instead of a dead end. |
| `get_element` | `profile, prop?, uid?, selector?, limit?, max_chars?, name?` | Reads one property of one element: `text`, `value`, `attribute` (needs `name`), `state`, `box`, `style` (needs `name`) or `count`. Returns the bare value, never a JSON wrapper. Exactly one of `uid` or `selector`, except `count`, which takes a selector. |
| `screenshot` | `profile, full_page?, uid?, max_width?` | A PNG of the viewport, the full page, or one element's bounding box. `max_width` downscales and returns the coordinate multiplier alongside the image, which `click_at` needs. |
| `get_html` | `profile, selector?, max_chars?, strip_scripts?, mode?` | Post-JavaScript markup or text. `selector` scopes to the first match. `mode='html'` (default, scripts stripped) or `'text'` for `innerText`. Capped at `max_chars`, default 20000, `<=0` for unlimited. |

Screenshots are the most expensive thing you can ask for, and the usage data says they are
reached for more than twice as often as a snapshot. A snapshot usually answers the same
question for a fraction of the tokens, and `find` or `get_element` answer a narrower one
for less again. Reach for the image when the question is genuinely visual: layout,
rendering, a canvas. Keep the viewport small (`CAMOUFOX_VIEWPORT=1000x700` is a good
default for local development) because image cost scales with pixel count.

A value never comes back blank from `get_element`. A property that does not apply raises
and names the tag, a real but empty value reads `(empty)`, an absent attribute reads
`(not set)`, and a selector that matched several elements says so rather than hiding the
ambiguity.

## 🖱️ Interaction

| Tool | Key parameters | What it does |
|---|---|---|
| `click` | `profile, uid \| selector, double_click?, observe?` | Clicks an element. Pass exactly one of `uid` or a CSS `selector`. |
| `click_at` | `profile, (x, y) \| points, double_click?, observe?` | Clicks raw viewport coordinates, for canvases and anything without a uid. `points: [[x,y], ...]` clicks a batch in order. |
| `fill` | `profile, uid \| selector, value, clear_first?, observe?` | Sets a field's value. On a `<select>` it picks the option matching by value, then by visible label. |
| `fill_form` | `profile, fields` | Fills several fields at once: `fields = [{uid, value}, ...]`. |
| `press_key` | `profile, key` | Sends a key, for example `Enter` or `Control+A`. |
| `scroll` | `profile, direction, amount?, uid?` | Scrolls the page, or scrolls an element into view. |
| `upload_file` | `profile, uid, file_path` | Sets a file input's value. |
| `handle_dialog` | `profile, action, prompt_text?` | Accepts or dismisses a pending `alert`, `confirm` or `prompt`. |

### uid or selector

`click` and `fill` accept exactly one of the two. Passing both, or neither, is an
error rather than a silent preference.

Use a uid when you found the element in a snapshot. Use a selector when you already
know it (`selector="#email"`), which skips the snapshot entirely and is much cheaper.
The selector path is not a locator: the page is polled until the first match is visible, a
uid is minted for it, and the identical uid path takes over, so both paths behave the same
and neither marks the element. Supported syntax is plain CSS plus 2 extensions,
`:has-text("...")` and `text=...`, resolved per comma branch and unioned in document order.
Anything else raises an error naming what is supported rather than matching nothing. Engine
prefixes are refused only at the start of a selector, so `[role="button"]` and
`[data-testid="x"]` are ordinary CSS and work.

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
| `evaluate` | `profile, script, uids?, max_chars?, max_items?` | Runs JavaScript in the page and returns the JSON-serialised result. `uids` passes resolved elements into the script as arguments, so it does not have to re-find by selector something you already hold. Output is capped by default: `max_chars` on a string, `max_items` on an array, cut at the element boundary so the result still parses. |

## 🌐 Network

| Tool | Key parameters | What it does |
|---|---|---|
| `list_network_requests` | `profile, resource_types?, page_size?, page_idx?, include_preserved?` | Paginated request and response log for the active tab. |
| `get_network_request` | `profile, reqid, include_body?, max_body_size?` | Full headers and body for one request. |

## 🖥️ Console

| Tool | Key parameters | What it does |
|---|---|---|
| `list_console_messages` | `profile, levels?, limit?, include_preserved?` | Recent console messages, optionally filtered by level. |

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
