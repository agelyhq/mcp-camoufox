from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_handle_alert(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog", "profile": PROFILE})

    await evaluate(client, PROFILE, "setTimeout(() => alert('Test alert'), 0)")
    await asyncio.sleep(0.3)

    result = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "accept"})
    )
    assert result == "Dialog accepted", result
    # The dialog is consumed, not just reported: a second call finds nothing pending.
    # `"accept" in result.lower()` only echoed the argument the caller passed in.
    again = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "accept"})
    )
    assert again == "Error: NoPendingDialogError: No dialog is pending", again


async def test_handle_confirm_dismiss(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog", "profile": PROFILE})

    await evaluate(
        client, PROFILE, "setTimeout(() => { window._confirmResult = confirm('OK?') }, 0)"
    )
    await asyncio.sleep(0.3)

    result = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "dismiss"})
    )
    assert result == "Dialog dismissed", result
    # A dismissed confirm() resolves to false; "dismiss" in the tool's own echo of the
    # argument it was handed could never have proved the dialog was actually answered.
    assert await evaluate(client, PROFILE, "window._confirmResult") == "false"


async def test_handle_prompt(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog", "profile": PROFILE})

    await evaluate(
        client, PROFILE, "setTimeout(() => { window._promptResult = prompt('Name?') }, 0)"
    )
    await asyncio.sleep(0.3)

    result = tool_text(
        await client.call_tool(
            "handle_dialog",
            {"profile": PROFILE, "action": "accept", "prompt_text": "Hello from test"},
        )
    )
    assert result == "Dialog accepted", result

    stored = await evaluate(client, PROFILE, "window._promptResult")
    assert stored == '"Hello from test"', stored


async def test_handle_dialog_no_pending(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "accept"})
    )
    assert result == "Error: NoPendingDialogError: No dialog is pending"


async def test_handle_dialog_invalid_action(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/dialog", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "bogus"})
    )
    assert "error" in result.lower()
