from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, extract_uid, goto_and_find, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_list_console_messages_log(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/console", PROFILE, "Log message")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})
    await asyncio.sleep(0.5)

    result = tool_text(await client.call_tool("list_console_messages", {"profile": PROFILE}))
    assert "hello from log" in result


async def test_list_console_messages_error(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/console", PROFILE, "Error message")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})
    await asyncio.sleep(0.5)

    result = tool_text(
        await client.call_tool("list_console_messages", {"profile": PROFILE, "levels": ["error"]})
    )
    assert "something went wrong" in result


async def test_list_console_messages_filter_excludes(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    log_uid = extract_uid(snap, "Log message")
    err_uid = extract_uid(snap, "Error message")

    await client.call_tool("click", {"profile": PROFILE, "uid": log_uid})
    await client.call_tool("click", {"profile": PROFILE, "uid": err_uid})
    await asyncio.sleep(0.5)

    result = tool_text(
        await client.call_tool("list_console_messages", {"profile": PROFILE, "levels": ["error"]})
    )
    assert "something went wrong" in result
    assert "hello from log" not in result


async def test_list_console_messages_limit(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/console", PROFILE, "Log multiple")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})
    await asyncio.sleep(0.5)

    result = tool_text(
        await client.call_tool("list_console_messages", {"profile": PROFILE, "limit": 2})
    )
    assert "multi-3" in result
    assert "multi-4" in result
    assert "multi-0" not in result


async def test_list_console_messages_empty(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console", "profile": PROFILE})

    result = tool_text(await client.call_tool("list_console_messages", {"profile": PROFILE}))
    assert "No console messages" in result
