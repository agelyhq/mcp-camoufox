from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import extract_uid, tool_text


async def test_single_click(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": "test"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Click me")

    result = tool_text(await client.call_tool("click", {"uid": uid}))
    assert "clicked" in result.lower()

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('click-output').textContent"},
        )
    )
    assert "single click detected" in js.lower()


async def test_double_click(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": "test"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Double-click me")

    result = tool_text(await client.call_tool("click", {"uid": uid, "double_click": True}))
    assert "clicked" in result.lower()

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('dblclick-output').textContent"},
        )
    )
    assert "double click detected" in js.lower()


async def test_click_counter(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": "test"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Count clicks")

    await client.call_tool("click", {"uid": uid})
    await client.call_tool("click", {"uid": uid})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('counter-output').textContent"},
        )
    )
    assert "2" in js


async def test_click_invalid_uid(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": "test"})
    result = tool_text(await client.call_tool("click", {"uid": "e99999"}))
    assert "error" in result.lower()


async def test_click_bad_uid_format(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": "test"})
    result = tool_text(await client.call_tool("click", {"uid": "invalid"}))
    assert "error" in result.lower()
