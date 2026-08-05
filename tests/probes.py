"""The instrument the marker tests read: everything a page could notice about us.

One object in the page's own realm counts what an automation layer can leave behind: a
branded event on an element, any mutation of the document, a ``MutationObserver`` built
in the page realm, and any listener added to ``window``. :mod:`tests.test_no_markers`
asserts that our footprint is empty; :mod:`tests.test_driver_footprint` pins the one
driver-level artifact that is not ours. How the tally is taken lives here, once.

Two actors other than us can reach the page, and both are accounted for rather than
assumed away. Camoufox adds uBlock Origin to every launch of its own accord
(``exclude_addons`` is the only way out and nothing passes it), so
``CAMOUFOX_ADDON_URLS=""`` drops this server's own default, the cookie blocker that
writes a class onto <html>, and not the browser's extension. That extension has no filter
for a loopback host and was measured inserting nothing into one, from document_start
onwards; its one page-writing path appends a <script> to <head> and removes it again,
which the record format below names outright rather than leaving as a bare count. The
other actor is the HTML parser, which is why :func:`arm_probes` refuses an unfinished
document.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, server_for
from tests.waits import poll_until

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


def probe_server(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> FastMCP:
    """A server with this project's own default addon dropped (see the module docstring)."""
    return server_for(monkeypatch, data_dir, CAMOUFOX_ADDON_URLS="")


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
