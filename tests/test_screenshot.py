from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, goto_and_find

if TYPE_CHECKING:
    from fastmcp import Client


async def test_screenshot_viewport(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    result = await client.call_tool("screenshot", {"profile": PROFILE})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100


async def test_screenshot_full_page(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    result = await client.call_tool("screenshot", {"profile": PROFILE, "full_page": True})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100


async def test_screenshot_element(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/screenshot", PROFILE, "Index")

    result = await client.call_tool("screenshot", {"profile": PROFILE, "uid": uid})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100
