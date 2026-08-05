"""A sub-frame navigating must not empty what the tab captured.

``framenavigated`` fires for every frame in a tab, so a page carrying an ad slot, a
captcha or any embed raises it long after its own load. Both per-tab monitors used to
rotate their buffers on that event, which moved the document's own requests and console
messages into the preserved buffer and cleared the live one: the default
``list_network_requests`` answered "No network requests captured." on a page that had
just finished loading, and every request still in flight stayed "pending" forever
because the pending table was cleared with it.

The assertions below are about the DEFAULT listing (``include_preserved`` left off),
because that is the one an agent calls. They are about what the page requested AFTER it
loaded: the document request of the page itself is issued before its own main-frame
navigation commits, so it legitimately sits in the preserved buffer and always has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE
from tests.waits import poll_tool_or_last, poll_tool_text, wait_predicate

if TYPE_CHECKING:
    from fastmcp import Client

# The page fetches once on load, then repoints its iframe 300 ms later and announces it
# on the same tick. Waiting for that milestone rather than for a fixed 2 s is what makes
# this file mean anything: slept through, the sub-frame navigation may not have happened
# yet, the buffer rotation under test is never triggered, and both tests pass covering
# nothing. The predicate is strictly stronger than the sleep, since it implies the load
# event fired and the page's own fetch resolved.
_NAVIGATED_JS = "document.getElementById('status').textContent === 'subframe navigated'"


def _one_completed_fetch(listing: str) -> bool:
    fetch_lines = [line for line in listing.splitlines() if " fetch " in line]
    return len(fetch_lines) == 1 and "pending" not in fetch_lines[0]


async def test_a_subframe_navigation_keeps_the_tab_s_requests(
    client: Client, flask_server: str
) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/subframe", "profile": PROFILE})
    await wait_predicate(client, PROFILE, _NAVIGATED_JS)

    # The monitors are fed by protocol events that can land after an evaluate round
    # trip, so the page-side milestone alone does not settle the listing.
    listing = await poll_tool_or_last(
        client, "list_network_requests", {"profile": PROFILE}, _one_completed_fetch
    )

    assert "No network requests captured." not in listing, listing
    # The fetch the page issued on load, and the sub-frame's first document, both
    # predate the sub-frame navigation. Rotating on that event hid them: the listing
    # reported 1 request of 1 on a page that had made 3.
    fetch_lines = [line for line in listing.splitlines() if " fetch " in line]
    assert len(fetch_lines) == 1, listing
    # It completed long before the sub-frame moved, and clearing the pending table with
    # the ring left requests like it reading "pending" for the rest of the session.
    assert "pending" not in fetch_lines[0], fetch_lines[0]


async def test_a_subframe_navigation_keeps_the_tab_s_console(
    client: Client, flask_server: str
) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/subframe", "profile": PROFILE})
    await wait_predicate(client, PROFILE, _NAVIGATED_JS)

    messages = await poll_tool_text(
        client, "list_console_messages", {"profile": PROFILE}, "parent loaded"
    )

    assert "parent loaded" in messages, messages
