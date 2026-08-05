"""What a page can and cannot observe about the element store, measured not assumed.

00_boot.js captures the built-ins the store needs when it first runs, and calls them
through saved references ever after. A page that replaces one of them later therefore
counts nothing, whether the store is walking its own table or an action op is building
an event, a selection or a file transfer.

Both tests patch AFTER a first snapshot, so the store is already booted and the question
is only about later patches. That is the half the capture can win. What it cannot win is
stated in `docs/anti-bot.md`: a page that patches BEFORE our first evaluate does see us,
because our JS runs in the page's own realm, and there is no reachable realm where it
would not.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# A contenteditable the probe page does not carry, so the getSelection/createRange
# branch of prepareFill is exercised. Added before the hooks so page setup is not
# counted.
ADD_RICH_FIELD_JS = """
(() => {
  const rich = document.createElement('div');
  rich.id = 'probe-rich';
  rich.setAttribute('contenteditable', 'true');
  rich.setAttribute('aria-label', 'Rich notes');
  rich.textContent = 'old';
  document.body.appendChild(rich);
  return 1;
})()
"""

# The globals 60_actions.js resolves at call time. Replacing them after boot is the
# whole detection: if a call goes through the page's replacement, the page sees it.
HOOK_UNCAPTURED_JS = """
(() => {
  window.__b = [];
  const seen = (what) => window.__b.push(what);
  const OrigEvent = window.Event;
  window.Event = function (type, init) {
    seen('Event:' + type);
    return new OrigEvent(type, init);
  };
  const OrigFile = window.File;
  window.File = function (bits, name, init) {
    seen('File');
    return new OrigFile(bits, name, init);
  };
  const OrigTransfer = window.DataTransfer;
  window.DataTransfer = function () {
    seen('DataTransfer');
    return new OrigTransfer();
  };
  const origSelection = window.getSelection;
  window.getSelection = function () {
    seen('getSelection');
    return origSelection.call(window);
  };
  return 1;
})()
"""

# The array and iterator methods the selector path used to reach for: `filter` and
# `slice` to narrow a match set, `sort` to put a union back in document order, `push`
# to collect, and the iterator behind every `for...of`. All of them belong to the page,
# so a page that replaces them after boot counts one hit per element examined -- on the
# path behind `find` and behind every selector-bound click and fill.
#
# Only calls whose receiver holds DOM elements are counted, which is what makes the
# assertion about US. The driver's own serializer runs in this same world on every
# evaluate and uses these methods freely on plain values; a list of elements is the one
# thing only a match set is made of. A `push` onto a still-empty array is therefore
# invisible here, so a regression that collects n elements registers n-1: enough, since
# the assertion is zero.
HOOK_COLLECTION_JS = """
(() => {
  window.__c = { filter: 0, slice: 0, sort: 0, push: 0, iterator: 0, nodelist: 0 };
  const overElements = (value) => {
    try {
      return value != null && value.length > 0 && value[0] instanceof Element;
    } catch (e) {
      return false;
    }
  };
  const wrap = (name) => {
    const original = Array.prototype[name];
    Array.prototype[name] = function () {
      if (overElements(this)) window.__c[name]++;
      return original.apply(this, arguments);
    };
  };
  wrap('filter');
  wrap('slice');
  wrap('sort');
  wrap('push');
  const origArray = Array.prototype[Symbol.iterator];
  Array.prototype[Symbol.iterator] = function () {
    if (overElements(this)) window.__c.iterator++;
    return origArray.call(this);
  };
  const origNodes = NodeList.prototype[Symbol.iterator];
  NodeList.prototype[Symbol.iterator] = function () {
    window.__c.nodelist++;
    return origNodes.call(this);
  };
  return 1;
})()
"""

# The primitives 00_boot.js walks its own table with. All three are captured, so a
# replacement installed after boot must count zero.
HOOK_CAPTURED_JS = """
(() => {
  window.__s = { iterator: 0, entries: 0, connected: 0 };
  const origIterator = Map.prototype[Symbol.iterator];
  Map.prototype[Symbol.iterator] = function () {
    window.__s.iterator++;
    return origIterator.call(this);
  };
  const origEntries = Map.prototype.entries;
  Map.prototype.entries = function () {
    window.__s.entries++;
    return origEntries.call(this);
  };
  const original = Object.getOwnPropertyDescriptor(Node.prototype, 'isConnected');
  Object.defineProperty(Node.prototype, 'isConnected', {
    configurable: true,
    get: function () {
      window.__s.connected++;
      return original.get.call(this);
    },
  });
  return 1;
})()
"""


async def test_globals_replaced_after_boot_are_not_observed(
    client: Client, flask_server: str
) -> None:
    """A page that replaces these globals after boot counts nothing.

    ``Event``, ``File``, ``DataTransfer``, ``window.getSelection`` and
    ``document.createRange`` are what the action ops build events and selections with.
    They are captured at boot and called through saved references, so replacing them
    later is a detection that never fires.

    This asserts an empty list rather than "not in", so a rename in the probe cannot make
    it pass by accident: the page must see literally nothing, whatever it hooked.

    It fails the moment a call site goes back to resolving one of these by name. If that
    happens deliberately, the fix is to move the name back into the observed half and say
    so in ``dom/js/00_boot.js``, not to relax the assertion.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})
    assert await evaluate(client, PROFILE, ADD_RICH_FIELD_JS) == "1"

    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    select = extract_uid(snap, "Fruit choice")
    rich = extract_uid(snap, "Rich notes")
    attachment = extract_uid(snap, "Attachment")

    assert await evaluate(client, PROFILE, HOOK_UNCAPTURED_JS) == "1"

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(b"boundary")
        upload = handle.name
    try:
        for name, args in (
            ("fill", {"profile": PROFILE, "uid": select, "value": "Cherry"}),
            ("fill", {"profile": PROFILE, "uid": rich, "value": "new text"}),
            ("upload_file", {"profile": PROFILE, "uid": attachment, "file_path": upload}),
        ):
            result = tool_text(await client.call_tool(name, args))
            assert not result.startswith(("Error:", "Timeout:")), f"{name}: {result}"
    finally:
        Path(upload).unlink(missing_ok=True)

    seen = json.loads(await evaluate(client, PROFILE, "window.__b"))
    assert seen == [], f"the page observed our calls through replaced globals: {seen}"


async def test_the_store_walks_its_own_table_through_captured_primitives(
    client: Client, flask_server: str
) -> None:
    """The other half: the table walk itself reveals nothing to a later patch.

    ``sweep`` runs at the head of every capture and ``pick`` on every uid-addressed
    call, so a page that replaces ``Map.prototype[Symbol.iterator]``,
    ``Map.prototype.entries`` or the ``Node.prototype.isConnected`` getter after boot
    would otherwise get a hit per snapshot and per uid. All three are held in B, so
    the counters stay at zero.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    button = extract_uid(snap, "Probe button")

    assert await evaluate(client, PROFILE, HOOK_CAPTURED_JS) == "1"

    tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    tool_text(await client.call_tool("get_element", {"profile": PROFILE, "uid": button}))
    tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    counts = json.loads(await evaluate(client, PROFILE, "window.__s"))
    assert counts == {"iterator": 0, "entries": 0, "connected": 0}, counts


async def test_the_selector_path_collects_matches_without_the_pages_array_methods(
    client: Client, flask_server: str
) -> None:
    """The third half, and the one that was missing: `find` and selector-bound actions.

    The locate path parses a selector, queries each branch, filters on text, merges the
    branches back into document order and caps the result. Written with `for...of`,
    `.filter`, `.slice`, `.sort` and `.push` that is 5 page-owned entry points on the
    single path an operator uses most, and a page hooking any of them counts every
    element examined -- a per-element signal, not a per-call one.

    A selector list with a `:has-text()` branch is deliberate: it is the shape that
    exercises the union merge and the text filter together, which is where the array
    methods lived.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})
    tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    assert await evaluate(client, PROFILE, HOOK_COLLECTION_JS) == "1"

    for name, args in (
        ("find", {"profile": PROFILE, "css": "button:has-text('Probe'), h2, input"}),
        ("find", {"profile": PROFILE, "role": "button", "name": "Probe"}),
        ("find", {"profile": PROFILE, "text": "Deep button"}),
        ("click", {"profile": PROFILE, "selector": "#probe-btn"}),
        ("fill", {"profile": PROFILE, "selector": "#probe-text", "value": "Ada"}),
    ):
        result = tool_text(await client.call_tool(name, args))
        assert not result.startswith(("Error:", "Timeout:")), f"{name}: {result}"

    counts = json.loads(await evaluate(client, PROFILE, "window.__c"))
    assert counts == dict.fromkeys(counts, 0), counts
