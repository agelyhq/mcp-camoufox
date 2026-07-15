from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, extract_uid, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_drag_source_to_target(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/drag", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    from_uid = extract_uid(snap, "Drag handle")
    to_uid = extract_uid(snap, "Drop target")

    result = tool_text(
        await client.call_tool("drag", {"profile": PROFILE, "from_uid": from_uid, "to_uid": to_uid})
    )
    assert "dragged" in result.lower()
    await asyncio.sleep(0.3)

    js = await text_content(client, PROFILE, "drag-output")
    assert js == '"dropped"'


async def test_drag_invalid_uid(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/drag", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    to_uid = extract_uid(snap, "Drop target")

    result = tool_text(
        await client.call_tool("drag", {"profile": PROFILE, "from_uid": "e99999", "to_uid": to_uid})
    )
    assert "error" in result.lower()
    assert "stale uid" in result.lower()
