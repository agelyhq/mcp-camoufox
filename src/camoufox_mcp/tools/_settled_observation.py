"""The ``observe`` block, held back until the tab has stopped moving.

An action's observation must describe the document the action led to, so it waits for
the same evidence the "[page]" line waits for (``_page_line``), then verifies that the
tab did not move again while it was being read.
"""

from __future__ import annotations

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

# What the caller is told when the tab keeps navigating through both capture
# attempts, a chain of redirects above all. Silence would be worse: it asked to be
# shown the page and has to know it was not.
_KEPT_MOVING = (
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
    await _settled_document(page, tool)
    at_capture = page.url
    block = await observe_suffix(page, mode)
    if page.url == at_capture:
        return block
    await _document_ready(page)
    at_capture = page.url
    block = await observe_suffix(page, mode)
    return block if page.url == at_capture else _KEPT_MOVING


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
