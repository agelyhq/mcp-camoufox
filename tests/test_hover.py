from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, goto_and_find, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_hover_reveals_state(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/hover", PROFILE, "Hover me")

    result = tool_text(await client.call_tool("hover", {"profile": PROFILE, "uid": uid}))
    assert "hovered" in result.lower()
    await asyncio.sleep(0.2)

    js = await text_content(client, PROFILE, "hover-output")
    assert js == '"hovered"'


async def test_hover_invalid_uid(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/hover", "profile": PROFILE})

    result = tool_text(await client.call_tool("hover", {"profile": PROFILE, "uid": "e99999"}))
    assert "error" in result.lower()
    assert "stale uid" in result.lower()
