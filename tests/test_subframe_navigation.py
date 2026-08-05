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

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# The page fetches once on load, then repoints its iframe 300ms later.
_SETTLE_S = 2.0


async def test_a_subframe_navigation_keeps_the_tab_s_requests(
    client: Client, flask_server: str
) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/subframe", "profile": PROFILE})
    await asyncio.sleep(_SETTLE_S)

    listing = tool_text(await client.call_tool("list_network_requests", {"profile": PROFILE}))

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
    await asyncio.sleep(_SETTLE_S)

    messages = tool_text(await client.call_tool("list_console_messages", {"profile": PROFILE}))

    assert "parent loaded" in messages, messages
