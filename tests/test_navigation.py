from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_back_forward_reload(client: Client, flask_server: str) -> None:
    first = f"{flask_server}/click"
    second = f"{flask_server}/snapshot"

    await client.call_tool("navigate", {"url": first, "profile": PROFILE})
    await client.call_tool("navigate", {"url": second, "profile": PROFILE})

    back = tool_text(await client.call_tool("go_back", {"profile": PROFILE}))
    assert "went back" in back.lower()
    assert "/click" in back

    forward = tool_text(await client.call_tool("go_forward", {"profile": PROFILE}))
    assert "went forward" in forward.lower()
    assert "/snapshot" in forward

    reloaded = tool_text(await client.call_tool("reload", {"profile": PROFILE}))
    assert "reloaded" in reloaded.lower()
    assert "/snapshot" in reloaded


async def test_go_forward_no_history(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(await client.call_tool("go_forward", {"profile": PROFILE}))
    assert "no next page" in result.lower()
