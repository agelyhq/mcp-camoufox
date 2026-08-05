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
    # The wrapper renders a TimeoutError as "Timeout: ...", never "Error: ...", and the
    # message has to name the selector that never appeared: `"timeout" in result or
    # "error" in result` accepted any failure at all, including a stale-uid or a
    # ValueError from argument validation.
    assert result == "Timeout: selector '#nonexistent' did not appear within 1000ms", result


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
    assert result == (
        "Error: ValueError: invalid condition 'bogus'; valid values: "
        "'load', 'selector', 'network_idle', 'predicate'"
    ), result


async def test_wait_for_predicate(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "predicate",
                "expression": "document.querySelector('#delayed-3s') !== null",
                "timeout": 10000,
            },
        )
    )
    assert "condition met" in result.lower()
    assert "predicate" in result.lower()


async def test_wait_for_predicate_with_return(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "predicate",
                "expression": "!!document.getElementById('delayed-3s')",
                "return_expression": "document.getElementById('delayed-3s').textContent",
                "timeout": 10000,
            },
        )
    )
    assert "condition met" in result.lower()
    assert "3 seconds" in result


async def test_wait_for_predicate_missing_expression(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("wait_for", {"profile": PROFILE, "condition": "predicate"})
    )
    assert result == ("Error: ValueError: condition 'predicate' requires a non-empty expression"), (
        result
    )


async def test_wait_for_predicate_timeout(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/wait-for", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "predicate",
                "expression": "!!document.getElementById('never-exists')",
                "timeout": 1000,
            },
        )
    )
    # A predicate timeout is actionable only if it reports what the predicate last
    # returned, which is the whole point of the diagnosis: 23.8% of real
    # wait_for(predicate) calls burned the full budget and said nothing useful.
    assert result == "Timeout: predicate stayed falsy for 1000ms; last value: false", result
