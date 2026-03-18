from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_take_snapshot(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": "test"})

    snap = tool_text(await client.call_tool("take_snapshot", {}))
    assert "e0" in snap or "e1" in snap
    assert "heading" in snap.lower() or "button" in snap.lower() or "link" in snap.lower()


async def test_snapshot_contains_uids(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": "test"})

    snap = tool_text(await client.call_tool("take_snapshot", {}))
    assert "Click me" in snap
    assert "Double-click" in snap

    import re

    uids = re.findall(r"e\d+", snap)
    assert len(uids) >= 3


async def test_snapshot_no_session_error(client: Client) -> None:
    result = tool_text(await client.call_tool("take_snapshot", {}))
    assert "error" in result.lower() or "no" in result.lower()
