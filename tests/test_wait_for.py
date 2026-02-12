from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_wait_for_selector(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for"})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {"condition": "selector", "selector": "#delayed-3s", "timeout": 10000},
        )
    )
    assert "found" in result.lower()


async def test_wait_for_timeout(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for"})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {"condition": "selector", "selector": "#nonexistent", "timeout": 1000},
        )
    )
    assert "timeout" in result.lower() or "error" in result.lower()


async def test_wait_for_load(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for"})

    result = tool_text(await client.call_tool("wait_for", {"condition": "load"}))
    assert "loaded" in result.lower() or "load" in result.lower()


async def test_wait_for_idle(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for"})

    result = tool_text(await client.call_tool("wait_for", {"condition": "idle", "timeout": 10000}))
    assert "idle" in result.lower()


async def test_wait_for_invalid_condition(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for"})

    result = tool_text(await client.call_tool("wait_for", {"condition": "bogus"}))
    assert "error" in result.lower()
