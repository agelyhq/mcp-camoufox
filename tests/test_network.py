from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, goto_and_find, tool_text
from tests.waits import completed_entry, poll_tool_or_last, reqid_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import Client


def _completed(url_fragment: str) -> Callable[[str], bool]:
    """Accept a listing once ``url_fragment`` is captured AND has a status."""
    return lambda listing: completed_entry(listing, url_fragment) is not None


async def test_list_network_requests(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/network", PROFILE, "Fetch /api/data")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    # "Captured a COMPLETED request" is what the old 1.5 s nap was buying, so that is
    # the condition polled and the condition asserted.
    result = await poll_tool_or_last(
        client, "list_network_requests", {"profile": PROFILE}, _completed("/api/data")
    )
    assert completed_entry(result, "/api/data") is not None, result


async def test_get_network_request_details(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/network", PROFILE, "Fetch /api/data")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    listing = await poll_tool_or_last(
        client, "list_network_requests", {"profile": PROFILE}, _completed("/api/data")
    )
    # The id of the request the click made, not of whatever landed on the tab first: a
    # favicon probe or an asset added to the page later used to retarget the whole test.
    reqid = reqid_for(listing, "/api/data")

    detail = tool_text(
        await client.call_tool("get_network_request", {"profile": PROFILE, "reqid": reqid})
    )
    # The report is a fixed set of labelled sections; assert on the guaranteed
    # fields and the concrete 200 status rather than an incidental substring.
    assert f"Request [{reqid}]" in detail
    assert "Resource type:" in detail
    assert "Status: 200" in detail
    assert "Request headers:" in detail
    assert "Response headers:" in detail


async def test_get_network_request_unknown_id(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/network", "profile": PROFILE})

    detail = tool_text(
        await client.call_tool("get_network_request", {"profile": PROFILE, "reqid": 999999})
    )
    assert "no request found" in detail.lower()


async def test_list_network_requests_filter(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/network", PROFILE, "POST /api/echo")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    result = await poll_tool_or_last(
        client,
        "list_network_requests",
        {"profile": PROFILE, "resource_types": ["fetch", "xhr"]},
        _completed("/api/echo"),
    )
    assert "/api/echo" in result, result


async def test_a_binary_post_body_does_not_poison_the_next_tool_call(
    client: Client, flask_server: str
) -> None:
    """The regression test for the most frequent error this product ever had.

    ``Request.post_data`` is a STRICT utf-8 decode of the raw body, so a page posting
    bytes that are not valid utf-8 (a protobuf beacon, a multipart upload, a gzipped
    payload, a Blob) used to raise ``UnicodeDecodeError`` inside Playwright's event
    dispatch, from our own ``page.on("request")`` listener.

    Playwright does not let that surface where it happens. It stashes the exception on
    the connection and re-raises it at the top of the NEXT api call, where its error
    rewriter does ``type(exc)(message)``. ``UnicodeDecodeError`` needs 5 constructor
    arguments, so rebuilding it from 1 raises ``TypeError: function takes exactly 5
    arguments (1 given)`` on an unrelated tool, before any I/O, with no traceback
    anywhere. That is the 133 occurrences of issue #13.

    So the assertion that matters is not about the POST at all: it is that the call
    AFTER it still works. Reverting ``read_post_data`` in ``sessions/network.py`` to
    ``request.post_data`` makes the ``evaluate`` below fail, which is what the previous
    tests in this file did not catch.
    """
    await client.call_tool("navigate", {"profile": PROFILE, "url": f"{flask_server}/network"})

    posted = tool_text(
        await client.call_tool(
            "evaluate",
            {
                "profile": PROFILE,
                # 0x96 is a continuation byte with no lead byte: never valid utf-8.
                "script": (
                    "(async () => {"
                    "  const body = new Uint8Array([0x00, 0x96, 0xfe, 0xff, 0x01]);"
                    f"  const r = await fetch('{flask_server}/api/echo', "
                    "    {method: 'POST', body, headers: {'Content-Type': 'application/octet-stream'}});"
                    "  return r.status;"
                    "})()"
                ),
            },
        )
    )
    assert "200" in posted, posted

    # The poison, if any, is latched on the connection and fires on the next call.
    for attempt in range(3):
        result = tool_text(
            await client.call_tool("evaluate", {"profile": PROFILE, "script": "1 + 1"})
        )
        assert result.strip() == "2", f"call {attempt + 1} after a binary POST returned {result!r}"

    entries = tool_text(await client.call_tool("list_network_requests", {"profile": PROFILE}))
    assert "/api/echo" in entries, entries
