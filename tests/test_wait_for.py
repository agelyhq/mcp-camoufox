from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_wait_for_selector(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "selector",
                "selector": "#delayed-3s",
                "timeout": 10000,
            },
        )
    )
    assert "condition met" in result.lower()
    assert "#delayed-3s" in result


async def test_wait_for_timeout(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "selector",
                "selector": "#nonexistent",
                "timeout": 1000,
            },
        )
    )
    assert "timeout" in result.lower() or "error" in result.lower()


async def test_wait_for_load(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("wait_for", {"profile": PROFILE, "condition": "load"})
    )
    assert "condition met" in result.lower()
    assert "load" in result.lower()


async def test_wait_for_network_idle(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "wait_for", {"profile": PROFILE, "condition": "network_idle", "timeout": 10000}
        )
    )
    assert "condition met" in result.lower()
    assert "network_idle" in result.lower()


async def test_wait_for_invalid_condition(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("wait_for", {"profile": PROFILE, "condition": "bogus"})
    )
    assert "error" in result.lower()
