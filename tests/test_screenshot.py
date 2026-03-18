from __future__ import annotations

from fastmcp import Client  # noqa: TC002


async def test_take_screenshot_viewport(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": "test"})

    result = await client.call_tool("take_screenshot", {})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100


async def test_take_screenshot_full_page(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": "test"})

    result = await client.call_tool("take_screenshot", {"full_page": True})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100
