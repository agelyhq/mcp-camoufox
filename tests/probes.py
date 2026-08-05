"""The instrument the marker tests read: everything a page could notice about us.

One object in the page's own realm counts what an automation layer can leave behind: a
branded event on an element, any mutation of the document, a ``MutationObserver`` built
in the page realm, and any listener added to ``window``. :mod:`tests.test_no_markers`
asserts that our footprint is empty; :mod:`tests.test_driver_footprint` pins the one
driver-level artifact that is not ours. How the tally is taken lives here, once.

Two actors other than us could reach the page, and neither is assumed away. Camoufox adds
uBlock Origin to every launch of its own accord, whatever ``CAMOUFOX_ADDON_URLS`` says, and
its one page-writing path appends a <script> to <head> and removes it again: 3 records that
were read as ours on a release runner. So :func:`probe_server` drops this server's own
default addon AND Camoufox's bundled one, and :func:`extensions_after_closing` reads back
from the browser's own records that the launch really held none, because a setting is a
request and this claim needs a measurement. The other actor is the HTML parser, which is why
:func:`arm_probes` refuses an unfinished document. What is left able to write to the page is
this server, the page's own script, and the driver.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, server_for, tool_text
from tests.waits import poll_until, poll_until_sync

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest
    from fastmcp import Client, FastMCP

# Armed AFTER navigation, so nothing it installs is wiped by a load, and it returns the
# readyState it saw so the caller can refuse a document the parser is still building.
#
# A mutation is recorded as "<type>:<attributeName> on <target> +<added> -<removed>",
# type and attribute name first so a caller can match on the prefix. A bare count is
# unactionable: it says 3 nodes appeared and nothing about whose they were, which is the
# whole difference between a leak of ours and the parser finishing its work.
ARM_PROBES_JS = """
(() => {
  const describe = (node) => {
    if (!node) return '?';
    if (node.nodeType !== 1) return node.nodeName;
    const cls = (node.getAttribute('class') || '').trim();
    return node.nodeName.toLowerCase() + (node.id ? '#' + node.id : '')
      + (cls ? '.' + cls.split(' ').join('.') : '');
  };
  const names = (nodes) => Array.from(nodes).map(describe).join(',');
  const describeRecord = (r) => r.type + ':' + (r.attributeName || '')
    + ' on ' + describe(r.target)
    + (r.addedNodes.length ? ' +' + names(r.addedNodes) : '')
    + (r.removedNodes.length ? ' -' + names(r.removedNodes) : '');
  window.__p = { marks: [], mutations: [], listeners: [], mo: 0 };
  document.addEventListener('__playwright_mark_target__', () => window.__p.marks.push('mark'), true);
  document.addEventListener('__playwright_unmark_target__', () => window.__p.marks.push('unmark'), true);
  const OrigMO = window.MutationObserver;
  window.MutationObserver = function (cb) { window.__p.mo++; return new OrigMO(cb); };
  new OrigMO((records) => {
    records.forEach((r) => window.__p.mutations.push(describeRecord(r)));
  }).observe(document.documentElement, { attributes: true, childList: true, subtree: true });
  const add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    try { if (this === window) window.__p.listeners.push(String(type)); } catch (e) { /* ignore */ }
    return add.call(this, type, fn, opts);
  };
  return document.readyState;
})()
"""

READ_PROBES_JS = "window.__p"

# The capture-phase pointer set a driver's injected script installs on window.
INTERCEPTOR_EVENTS = ("pointerdown", "auxclick", "touchcancel")

# A negative claim has no appearance to wait for: the assertions say nothing arrived.
# This is the window in which a leak would have had to show up, so it is a detection
# window and not a settle time. It can only fail open, which is stated here because a
# slower runner weakens the claim rather than breaking the run.
LEAK_WINDOW_S = 0.8
# Bound on the positive waits below. The effect is asynchronous, so the loop stops on
# the effect; the assertion that follows stays the verdict.
PROBE_DEADLINE_S = 10.0
PROBE_INTERVAL_S = 0.1

# The addon id Camoufox's own DefaultAddons.UBO installs under. Camoufox names the addon by
# download URL, and Firefox records it by id, so the id is spelled out here.
UBO_ID = "uBlock0@raymondhill.net"

# Guardrail on the 2 extension records existing at all, once the browser has exited. It is
# not the wait that makes the reading trustworthy: closing the session is (see below).
EXTENSION_RECORD_DEADLINE_S = 10.0

_UUID_PREF = re.compile(r'user_pref\("extensions\.webextensions\.uuids", (".*")\);')
_SHIPPED_LOCATION = "app-builtin"


def probe_server(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, *, bundled_addons: str = "false"
) -> FastMCP:
    """A server whose browser holds no extension at all (see the module docstring).

    ``bundled_addons="true"`` is the control: it puts Camoufox's own uBlock Origin back
    and changes nothing else, so the 2 browsers differ in exactly 1 setting.
    """
    return server_for(
        monkeypatch,
        data_dir,
        CAMOUFOX_ADDON_URLS="",
        CAMOUFOX_BUNDLED_ADDONS=bundled_addons,
    )


async def extensions_after_closing(client: Client, data_dir: Path) -> list[str]:
    """Close the session, then read which extensions the browser it ran held.

    The close is what makes the answer deterministic, and it is asserted here: a profile
    that was never active would leave an unwritten record reading as a clean browser.
    """
    closed = tool_text(await client.call_tool("close_session", {"profile": PROFILE}))
    assert closed.startswith(f"Closed session '{PROFILE}'"), closed
    return extensions_the_browser_held(data_dir)


def extensions_the_browser_held(data_dir: Path) -> list[str]:
    """The ids of the extensions the browser held, Firefox's own excluded.

    Firefox gives every webextension it loads a UUID and records the mapping in the
    profile's ``prefs.js``; the addons it ships itself are the ones its own
    ``extensions.json`` lists at an ``app-builtin`` location. The difference between the 2
    is every extension somebody added to this browser, and for uBlock Origin it is the
    only trace there is: Camoufox installs it temporarily, and a temporary install never
    reaches ``extensions.json``.

    **Call this only once the session is closed.** Firefox flushes prefs on a timer and
    again at shutdown, and a live browser was measured 1 run in 10 having flushed its own
    built-ins while uBlock Origin's UUID was still only in memory: an extension-holding
    browser read as empty. Reading after the exit is what makes the empty answer mean
    something. Both records are also required to be non-empty, so a Firefox that stopped
    keeping them fails here instead of reporting a clean browser.
    """
    profile_dir = data_dir / "profiles" / PROFILE
    poll_until_sync(
        lambda: bool(_uuid_ids(profile_dir)) and bool(_shipped_ids(profile_dir)),
        deadline=EXTENSION_RECORD_DEADLINE_S,
    )
    loaded, shipped = _uuid_ids(profile_dir), _shipped_ids(profile_dir)
    assert loaded, (
        f"prefs.js in {profile_dir} records no webextension UUID at all, so this "
        f"measurement cannot tell an extension-free browser from an unread one"
    )
    assert shipped, (
        f"extensions.json in {profile_dir} lists none of Firefox's own built-in addons, "
        f"so every id below would read as an extension somebody added"
    )
    return sorted(loaded - shipped)


def _uuid_ids(profile_dir: Path) -> set[str]:
    """Every extension id in the profile's UUID pref, empty while it is unwritten.

    The pref value is a JSON object inside a JS string literal, so it is decoded twice.
    Firefox rewrites ``prefs.js`` through a temporary file and a rename, so a read either
    sees the whole file or the previous one, never half of each.
    """
    prefs = profile_dir / "prefs.js"
    if not prefs.is_file():
        return set()
    match = _UUID_PREF.search(prefs.read_text())
    return set(json.loads(json.loads(match.group(1)))) if match else set()


def _shipped_ids(profile_dir: Path) -> set[str]:
    """The ids Firefox's own addon database marks as shipped with the browser."""
    database = profile_dir / "extensions.json"
    if not database.is_file():
        return set()
    addons = json.loads(database.read_text()).get("addons", [])
    return {
        addon["id"]
        for addon in addons
        if str(addon.get("location", "")).startswith(_SHIPPED_LOCATION)
    }


async def arm_probes(client: Client) -> None:
    """Arm the probes, refusing a document the parser has not finished.

    An unfinished parse appends the rest of the page while the probes are recording, and
    those appends arrive as childList records with no attribute record: measured, they
    are indistinguishable by count from a leak of ours. Tools report failure as a string
    rather than an exception, so a navigation that never completed is silent until here.
    """
    state = json.loads(await evaluate(client, PROFILE, ARM_PROBES_JS))
    assert state == "complete", (
        f"the probes were armed on a document in readyState '{state}': the parser's own "
        f"remaining appends would be recorded as mutations that are not ours"
    )


async def read_probes(client: Client) -> dict:
    return json.loads(await evaluate(client, PROFILE, READ_PROBES_JS))


async def probes_after_the_leak_window(client: Client) -> dict:
    """The probe tally read once the detection window above has fully elapsed."""
    await asyncio.sleep(LEAK_WINDOW_S)
    return await read_probes(client)


async def probes_when(client: Client, accept: Callable[[dict], bool]) -> dict:
    """Re-read the probes until ``accept`` holds, or the deadline runs out.

    Expiry is deliberately not an error: every caller asserts the effect it waited
    for on the value returned, so the assertion stays the verdict and keeps its own
    message as the diagnostic. The deadline only stops the loop.
    """
    probes, _ = await poll_until(
        lambda: read_probes(client),
        accept,
        deadline=PROBE_DEADLINE_S,
        interval=PROBE_INTERVAL_S,
    )
    return probes


def touched(probes: dict) -> bool:
    """Whether the control's deliberate attribute write was recorded, by prefix."""
    return any(m.startswith("attributes:data-touched") for m in probes["mutations"])
