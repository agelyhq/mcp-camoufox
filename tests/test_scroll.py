from __future__ import annotations

import asyncio

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_scroll_down(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/scroll", "profile": "test"})

    result = tool_text(await client.call_tool("scroll", {"direction": "down", "amount": 10}))
    assert "scrolled" in result.lower()
    await asyncio.sleep(0.3)

    js = tool_text(await client.call_tool("evaluate", {"script": "Math.round(window.scrollY)"}))
    assert int(js) > 0


async def test_scroll_element_into_view(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/scroll", "profile": "test"})

    js_before = tool_text(
        await client.call_tool("evaluate", {"script": "Math.round(window.scrollY)"})
    )

    await client.call_tool(
        "evaluate",
        {"script": "document.getElementById('section-10').scrollIntoView({behavior:'instant'})"},
    )
    await asyncio.sleep(0.3)

    js_after = tool_text(
        await client.call_tool("evaluate", {"script": "Math.round(window.scrollY)"})
    )
    assert int(js_after) > int(js_before)
