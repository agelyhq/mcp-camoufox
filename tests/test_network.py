from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, extract_first_reqid, goto_and_find, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_list_network_requests(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/network", PROFILE, "Fetch /api/data")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})
    await asyncio.sleep(1.5)

    result = tool_text(await client.call_tool("list_network_requests", {"profile": PROFILE}))
    assert "/api/data" in result


async def test_get_network_request_details(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/network", PROFILE, "Fetch /api/data")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})
    await asyncio.sleep(1.5)

    listing = tool_text(await client.call_tool("list_network_requests", {"profile": PROFILE}))
    reqid = extract_first_reqid(listing)

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
    await asyncio.sleep(2.5)

    result = tool_text(
        await client.call_tool(
            "list_network_requests",
            {"profile": PROFILE, "resource_types": ["fetch", "xhr"]},
        )
    )
    assert "/api/echo" in result
