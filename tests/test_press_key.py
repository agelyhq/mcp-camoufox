from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_press_arrow_key(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowRight"})
    )
    assert "pressed" in result.lower()

    js = await text_content(client, PROFILE, "key-display")
    assert "ArrowRight" in js


async def test_press_key_moves_marker(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowDown"})
    await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowDown"})

    js = await text_content(client, PROFILE, "position-output")
    assert "110" in js


async def test_press_key_combo(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    await client.call_tool("press_key", {"profile": PROFILE, "key": "Shift+A"})

    js = await text_content(client, PROFILE, "key-display")
    assert "Shift" in js
