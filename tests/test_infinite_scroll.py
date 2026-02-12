from __future__ import annotations

import asyncio

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_infinite_scroll_initial_load(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/infinite-scroll"})
    await asyncio.sleep(1)

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.querySelectorAll('.item').length"},
        )
    )
    count = int(js)
    assert count >= 10


async def test_infinite_scroll_loads_more_on_scroll(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/infinite-scroll"})
    await asyncio.sleep(1)

    before = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.querySelectorAll('.item').length"},
        )
    )

    await client.call_tool("scroll", {"direction": "down", "amount": 20})

    poll_js = f"""
    (async () => {{
        for (let i = 0; i < 30; i++) {{
            if (document.querySelectorAll('.item').length > {int(before)}) {{
                return document.querySelectorAll('.item').length;
            }}
            await new Promise(r => setTimeout(r, 200));
        }}
        return document.querySelectorAll('.item').length;
    }})()
    """
    after = tool_text(await client.call_tool("evaluate", {"script": poll_js}))
    assert int(after) > int(before)


async def test_infinite_scroll_network_requests(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/infinite-scroll"})
    await asyncio.sleep(1)

    result = tool_text(
        await client.call_tool(
            "list_network_requests",
            {"resource_types": ["fetch", "xhr"]},
        )
    )
    assert "/api/items" in result
