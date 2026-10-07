"""The ``observe`` block, held back until the tab has stopped moving.

An action's observation must describe the document the action led to, so it waits for
the same evidence the "[page]" line waits for (``_page_line``), then verifies that the
tab did not move again while it was being read.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from camoufox_mcp.tools._errors import log_swallowed
from camoufox_mcp.tools._observe import observe_suffix
from camoufox_mcp.tools._page_line import settled_url

if TYPE_CHECKING:
    from camoufox_mcp.sessions import Page

# page.url flips the moment a navigation commits, which is before the new document
# has a body, so a capture taken at that instant would return an almost empty tree.
# Waiting for DOMContentLoaded is answered from the lifecycle events Playwright has
# already recorded, so it costs nothing on a loaded document and adds no listener,
# no selector engine and nothing observable to the page.
_READY_BUDGET_MS = 1500

logger = logging.getLogger(__name__)

# The "[page]" line gives up on a navigation that has not committed within its own
# budget, a trade made for actions nobody asked to observe. An observation cannot make
# it: capturing then reads the document being replaced, and the result is either that
# departed page's content with no "[page]" line or an "Execution context was destroyed"
# note (measured: 5 of 40 navigating clicks under CPU contention, commits landing
# 1.5 s+ after the click). So an observation waits for the commit as long as the
# server has not answered, up to _COMMIT_CAP_S, a slow site's time to first byte; once
# it has answered, the commit is a browser-local hop, yet one that took over 1.5 s on 2
# of 40 clicks under 3x CPU oversubscription, hence _COMMIT_AFTER_ANSWER_S. An answer
# that never commits (a 204, a download) costs an observed action that much, no more.
_COMMIT_CAP_S = 10.0
_COMMIT_AFTER_ANSWER_S = 5.0
_POLL_INTERVAL_S = 0.01

# What the caller is told when the tab keeps navigating through both capture
# attempts, a chain of redirects above all. Silence would be worse: it asked to be
# shown the page and has to know it was not.
KEPT_MOVING = (
    "\n\n[observation skipped: the page navigated again while it was being read; "
    "call snapshot for the page you have now]"
)


async def settled_observation(page: Page, tool: str, mode: str | None) -> str:
    """The ``observe`` block for ``mode``, taken once the tab has stopped moving.

    An action that navigates returns as soon as the browser acknowledges the event,
    so capturing straight away read the document that was about to be replaced: the
    result then carried the departed page's tree between 2 contradictory ``[page]``
    lines, and every uid in that tree failed on the very next call. The capture is
    therefore held until the evidence the ``[page]`` line waits for has resolved,
    then verified: a tab that moved while it was being read is captured once more,
    and a tab that will not settle is named rather than described.

    Suppressing the observation instead would have been cheaper and is the wrong
    trade: the caller pays for one so it can act without a further snapshot, and the
    page it just landed on is the one it knows least about.

    ``mode`` is ``None`` for a tool that has no ``observe`` argument and ``"none"``
    for one that was not asked for an observation; both start no wait at all.
    """
    if not mode or mode == "none":
        return ""
    mark = page.doc_mark
    await _settled_document(page, tool)
    if mark is not None:
        await _committed(page, mark)
        await _document_ready(page)
    for _ in range(2):
        before = _position(page)
        block = await observe_suffix(page, mode)
        if _position(page) == before:
            return block
        # The tab moved, or asked for a new document, while it was being read: a
        # request first seen here is a navigation that missed the evidence window.
        await _committed(page, before[1])
        await _document_ready(page)
    return KEPT_MOVING


def _position(page: Page) -> tuple[str, int]:
    """Where the tab is, and the newest document it has asked for."""
    return page.url, page.network.last_document_reqid


async def _committed(page: Page, mark: int) -> None:
    """Wait for a navigation started after ``mark`` to commit, bounded as stated above."""
    started = last_unanswered = time.monotonic()
    network = page.network
    while network.last_document_reqid > mark:
        pending, unanswered = network.awaiting_commit()
        now = time.monotonic()
        if unanswered:
            last_unanswered = now
        if not pending or now - started >= _COMMIT_CAP_S:
            return
        if now - last_unanswered >= _COMMIT_AFTER_ANSWER_S:
            logger.debug("observation: document answered but not committed, capturing anyway")
            return
        await asyncio.sleep(_POLL_INTERVAL_S)


async def _settled_document(page: Page, tool: str) -> None:
    """Wait out a navigation the action may have started, then let it build.

    Best-effort by contract: the action has ALREADY succeeded, so a failure here
    must cost the caller its observation at worst, never its result.
    """
    try:
        await settled_url(page, tool, page.shown_url)
    except Exception as exc:
        log_swallowed(f"settling '{tool}' before its observation", exc)
    finally:
        # The wait is spent. Dropping the mark stops page_context_suffix repeating
        # it after the observation, which would double the cost of every observed
        # action that does not navigate.
        page.doc_mark = None
    await _document_ready(page)


async def _document_ready(page: Page) -> None:
    """Give the document the tab holds now time to reach DOMContentLoaded."""
    try:
        await page.raw.wait_for_load_state("domcontentloaded", timeout=_READY_BUDGET_MS)
    except Exception as exc:
        log_swallowed("waiting for the document to be ready", exc)
