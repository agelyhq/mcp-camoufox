from __future__ import annotations

import asyncio

from fastmcp import Client  # noqa: TC002

from tests.helpers import extract_uid, tool_text


async def test_list_console_messages_log(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Log message")

    await client.call_tool("click", {"uid": uid})
    await asyncio.sleep(0.5)

    result = tool_text(await client.call_tool("list_console_messages", {}))
    assert "hello from log" in result


async def test_list_console_messages_error(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Error message")

    await client.call_tool("click", {"uid": uid})
    await asyncio.sleep(0.5)

    result = tool_text(await client.call_tool("list_console_messages", {"levels": ["error"]}))
    assert "something went wrong" in result


async def test_list_console_messages_filter_excludes(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))

    log_uid = extract_uid(snap, "Log message")
    err_uid = extract_uid(snap, "Error message")

    await client.call_tool("click", {"uid": log_uid})
    await client.call_tool("click", {"uid": err_uid})
    await asyncio.sleep(0.5)

    result = tool_text(await client.call_tool("list_console_messages", {"levels": ["error"]}))
    assert "something went wrong" in result
    assert "hello from log" not in result


async def test_list_console_messages_limit(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Log multiple")

    await client.call_tool("click", {"uid": uid})
    await asyncio.sleep(0.5)

    result = tool_text(await client.call_tool("list_console_messages", {"limit": 2}))
    assert "multi-3" in result
    assert "multi-4" in result
    assert "multi-0" not in result


async def test_list_console_messages_empty(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/console"})

    result = tool_text(await client.call_tool("list_console_messages", {}))
    assert "No console messages" in result
