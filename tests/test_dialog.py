from __future__ import annotations

import asyncio

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_handle_alert(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog"})

    await client.call_tool("evaluate", {"script": "setTimeout(() => alert('Test alert'), 0)"})
    await asyncio.sleep(0.3)

    result = tool_text(await client.call_tool("handle_dialog", {"action": "accept"}))
    assert "accepted" in result.lower() or "handled" in result.lower()


async def test_handle_confirm_dismiss(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog"})

    await client.call_tool(
        "evaluate", {"script": "setTimeout(() => { window._confirmResult = confirm('OK?') }, 0)"}
    )
    await asyncio.sleep(0.3)

    result = tool_text(await client.call_tool("handle_dialog", {"action": "dismiss"}))
    assert "dismissed" in result.lower() or "handled" in result.lower()


async def test_handle_prompt(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog"})

    await client.call_tool(
        "evaluate",
        {"script": "setTimeout(() => { window._promptResult = prompt('Name?') }, 0)"},
    )
    await asyncio.sleep(0.3)

    result = tool_text(
        await client.call_tool(
            "handle_dialog", {"action": "accept", "prompt_text": "Hello from test"}
        )
    )
    assert "accepted" in result.lower() or "handled" in result.lower()


async def test_handle_dialog_no_pending(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog"})

    result = tool_text(await client.call_tool("handle_dialog", {"action": "accept"}))
    assert "no dialog" in result.lower() or "error" in result.lower()
