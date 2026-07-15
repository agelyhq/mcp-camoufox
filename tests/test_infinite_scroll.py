from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

COUNT_JS = "document.querySelectorAll('.item').length"


async def test_infinite_scroll_initial_load(client: Client, flask_server: str) -> None:
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/infinite-scroll", "profile": PROFILE}
    )
    await asyncio.sleep(1)

    js = await evaluate(client, PROFILE, COUNT_JS)
    assert int(js) >= 10


async def test_infinite_scroll_loads_more_on_scroll(client: Client, flask_server: str) -> None:
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/infinite-scroll", "profile": PROFILE}
    )
    await asyncio.sleep(1)

    before = int(await evaluate(client, PROFILE, COUNT_JS))

    # Several full-viewport scrolls to reliably reach the load threshold.
    for _ in range(6):
        await client.call_tool("scroll", {"profile": PROFILE, "direction": "down"})
        await asyncio.sleep(0.4)

    poll_js = f"""
    (async () => {{
        for (let i = 0; i < 30; i++) {{
            if (document.querySelectorAll('.item').length > {before}) {{
                return document.querySelectorAll('.item').length;
            }}
            await new Promise(r => setTimeout(r, 200));
        }}
        return document.querySelectorAll('.item').length;
    }})()
    """
    after = int(await evaluate(client, PROFILE, poll_js))
    assert after > before


async def test_infinite_scroll_network_requests(client: Client, flask_server: str) -> None:
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/infinite-scroll", "profile": PROFILE}
    )
    await asyncio.sleep(1)

    result = tool_text(
        await client.call_tool(
            "list_network_requests",
            {"profile": PROFILE, "resource_types": ["fetch", "xhr"]},
        )
    )
    assert "/api/items" in result
