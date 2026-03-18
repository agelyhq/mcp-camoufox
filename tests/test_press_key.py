from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_press_arrow_key(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": "test"})

    result = tool_text(await client.call_tool("press_key", {"key": "ArrowRight"}))
    assert "pressed" in result.lower()

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('key-display').textContent"},
        )
    )
    assert "ArrowRight" in js


async def test_press_key_moves_marker(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": "test"})

    await client.call_tool("press_key", {"key": "ArrowDown"})
    await client.call_tool("press_key", {"key": "ArrowDown"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('position-output').textContent"},
        )
    )
    assert "110" in js


async def test_press_key_combo(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": "test"})

    await client.call_tool("press_key", {"key": "Shift+A"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('key-display').textContent"},
        )
    )
    assert "Shift" in js
