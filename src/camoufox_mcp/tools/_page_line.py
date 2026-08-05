"""The "[page] <title> | <url>" line, and the wait that decides whether to emit it.

The line is one-directional evidence: when it is there, the tab is not where the agent
was last shown. Its absence proves nothing, and no text anywhere may claim otherwise.
A navigation that commits after the confirmation window closes carries no line, and
neither does one started by a tool outside ``PAGE_CONTEXT_TOOLS``, press_key above
all. Every such move is instead reported on the agent's next call, when the baseline
on the tab (``Page.shown_url``) is compared again.

``_settled_observation`` builds on the same wait: an action's ``observe`` block must
describe the document the action led to, so it waits for the same evidence before
capturing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from camoufox_mcp.tools._errors import log_swallowed

if TYPE_CHECKING:
    from camoufox_mcp.sessions import Page

logger = logging.getLogger(__name__)

# navigate is handled apart from the others: the caller supplied the destination, so
# its baseline is that destination and the line reports a redirect only.
NAVIGATE = "navigate"

# Actions that can start a navigation and return before it commits, and so pay for a
# confirmation window. press_key would qualify on principle, since Enter submits a
# form, and is deliberately left out: it has a 4.1 ms median over 903 real calls, 96%
# of them arrow keys inside a game loop, so the window would multiply the cost of the
# tool by roughly 50 for a case where a keystroke rarely navigates. A navigation an
# Enter starts is reported on the agent's next call, exactly like any navigation that
# commits after the window closes.
SETTLING_TOOLS = frozenset({"click", "click_at", "fill"})

# Every tool the page line is appended to. go_back and reload await their own
# navigation, so their URL is already final when the body returns.
PAGE_CONTEXT_TOOLS = SETTLING_TOOLS | frozenset({"go_back", "reload", NAVIGATE})

# A pointer or form action returns as soon as the browser acknowledges the event, so
# a navigation it started has not committed yet and page.url still reads the old
# document. Measured on this stack (camoufox 0.5.4 / Firefox 152, local server, cold
# profile), from the moment the tool body returns:
#
#   click that navigates : document request seen after 5-11 ms, page.url after 33-146 ms
#   click that stays put : no document request, no URL change, ever
#
# So the request is the early, reliable evidence and the URL change is the slow
# confirmation. Wait _EVIDENCE_WINDOW_S for either; extend to _COMMIT_BUDGET_S only
# once a document request proves a navigation is really under way. A non-navigating
# action therefore pays the short window once, and a real navigation gets a budget
# that survives a network round trip. Anything slower still surfaces on the agent's
# next call through Page.shown_url, so nothing is lost, only deferred.
_POLL_INTERVAL_S = 0.01
_EVIDENCE_WINDOW_S = 0.2
_COMMIT_BUDGET_S = 1.5
_RETRY_DELAY_S = 0.05

# Byte for byte the header the snapshot walk emits (dom/js/30_walk.js). The 2
# producers live either side of the Python/JS boundary so no constant can be shared;
# tests/test_page_context.py asserts they render the same bytes for the same page.
PAGE_LINE = "[page] {title} | {url}"


def note_page(page: Page, tool: str) -> None:
    """Record what the tab looked like before a tool runs.

    The baseline is seeded but never overwritten: an existing value is the last URL
    the agent was actually shown. The document-request mark is refreshed on every
    action that can navigate, because it is the evidence that one has started.
    """
    if page.shown_url is None:
        page.shown_url = page.url
    if tool in SETTLING_TOOLS:
        page.doc_mark = page.network.last_document_reqid


async def page_context_suffix(page: Page, tool: str, result: str, requested: Any = None) -> str:
    """Return ``"\\n[page] <title> | <url>"`` when the tab is not where the agent thinks.

    Appended by the ``@tool`` wrapper to the tools in ``PAGE_CONTEXT_TOOLS``: actions
    that can navigate as a side effect, which is precisely when an agent is surprised.
    For ``navigate`` the comparison is against the requested URL, so only a redirect
    is reported. The line is never emitted twice: a result that already carries it
    (``observe='snapshot'``) is left alone.

    Called for every tool, because every result that already shows the current URL
    updates the baseline, whatever tool produced it.

    Best-effort, like ``observe_suffix``: the action has ALREADY succeeded by the time
    this runs, so it swallows its own exceptions rather than turning a successful
    click into an error string. ``result`` is only read, never rewritten.
    """
    try:
        return await _suffix(page, tool, result, requested)
    except Exception as exc:
        log_swallowed(f"reading the page context for '{tool}'", exc)
        return ""


async def _suffix(page: Page, tool: str, result: str, requested: Any) -> str:
    expected = requested if tool == NAVIGATE else page.shown_url
    if not isinstance(expected, str):
        expected = None
    current = await settled_url(page, tool, expected)
    suffix = ""
    if tool in PAGE_CONTEXT_TOOLS and expected is not None and not same_place(current, expected):
        line = PAGE_LINE.format(title=await _title(page), url=current)
        if line not in result:
            joiner = "" if not result or result.endswith("\n") else "\n"
            suffix = f"{joiner}{line}"
    if suffix or current in result:
        # The agent has now seen this URL, either from our line or from the tool's
        # own output (navigate, snapshot, go_back, reload, an observation block).
        page.shown_url = current
    return suffix


async def settled_url(page: Page, tool: str, expected: str | None) -> str:
    """The tab's URL, giving a navigation the action may have started time to commit.

    Polls ``page.url``, which is a plain client-side property and costs no protocol
    traffic, and returns the moment it moves. The budget grows from the evidence
    window to the commit budget as soon as a document request shows a navigation is
    really under way, so a click that changes nothing is not made slow by clicks that
    do.
    """
    current = page.url
    mark = page.doc_mark
    if tool not in SETTLING_TOOLS or expected is None or mark is None:
        return current
    started = time.monotonic()
    budget = _EVIDENCE_WINDOW_S
    while same_place(current, expected) and time.monotonic() - started < budget:
        await asyncio.sleep(_POLL_INTERVAL_S)
        current = page.url
        if budget == _EVIDENCE_WINDOW_S and page.network.last_document_reqid > mark:
            budget = _COMMIT_BUDGET_S
    # The one place where "the agent was not told" can be a timing accident rather
    # than a decision, so leave the numbers behind for whoever reads the log.
    logger.debug(
        "page context settle: tool=%s moved=%s waited=%.0fms budget=%.0fms",
        tool,
        not same_place(current, expected),
        (time.monotonic() - started) * 1000,
        budget * 1000,
    )
    return current


async def _title(page: Page) -> str:
    """The document title, read once the new document can answer.

    The title is only ever needed at the instant a navigation committed, which is
    exactly when an evaluate can land between the old execution context being
    destroyed and the new one existing ("Execution context was destroyed"). One retry
    is enough: by then the context is pending, and Playwright waits for it.
    """
    try:
        return await page.title()
    except Exception:
        await asyncio.sleep(_RETRY_DELAY_S)
        return await page.title()


def same_place(current: str, expected: str) -> bool:
    """True when 2 URLs name the same page.

    A trailing "/" is ignored on both sides: a browser canonicalises
    "http://host" to "http://host/", and calling that a redirect would put a noise
    line on every navigate whose URL omits the slash.
    """
    return current == expected or current.removesuffix("/") == expected.removesuffix("/")
