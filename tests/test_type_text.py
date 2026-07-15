from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, goto_and_find, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def _focus_input(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/type-text", PROFILE, "Type here")
    await client.call_tool("click", {"profile": PROFILE, "uid": uid})


async def test_type_text_into_focused_input(client: Client, flask_server: str) -> None:
    await _focus_input(client, flask_server)

    result = tool_text(
        await client.call_tool("type_text", {"profile": PROFILE, "text": "hello world"})
    )
    assert "typed" in result.lower()
    assert "11" in result
    await asyncio.sleep(0.2)

    js = await text_content(client, PROFILE, "type-output")
    assert "hello world" in js


async def test_type_text_with_submit(client: Client, flask_server: str) -> None:
    await _focus_input(client, flask_server)

    result = tool_text(
        await client.call_tool("type_text", {"profile": PROFILE, "text": "query", "submit": True})
    )
    assert "enter" in result.lower()
    await asyncio.sleep(0.2)

    js = await text_content(client, PROFILE, "type-status")
    assert "submitted" in js
