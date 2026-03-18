from __future__ import annotations

import asyncio

from fastmcp import Client  # noqa: TC002

from tests.helpers import extract_first_reqid, extract_uid, tool_text


async def test_list_network_requests(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/network", "profile": "test"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Fetch /api/data")

    await client.call_tool("click", {"uid": uid})
    await asyncio.sleep(1.5)

    result = tool_text(await client.call_tool("list_network_requests", {}))
    assert "/api/data" in result


async def test_get_network_request_details(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/network", "profile": "test"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Fetch /api/data")

    await client.call_tool("click", {"uid": uid})
    await asyncio.sleep(1.5)

    listing = tool_text(await client.call_tool("list_network_requests", {}))
    reqid = extract_first_reqid(listing)

    detail = tool_text(
        await client.call_tool(
            "get_network_request",
            {"reqid": reqid},
        )
    )
    assert "200" in detail or "headers" in detail.lower()


async def test_list_network_requests_filter(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/network", "profile": "test"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "POST /api/echo")

    await client.call_tool("click", {"uid": uid})
    await asyncio.sleep(2.5)

    result = tool_text(
        await client.call_tool(
            "list_network_requests",
            {"resource_types": ["fetch", "xhr"]},
        )
    )
    assert "/api/echo" in result
