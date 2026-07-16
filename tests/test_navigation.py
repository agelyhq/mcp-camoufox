from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    import pytest
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


async def test_navigate_observe_none_is_default(client: Client, flask_server: str) -> None:
    result = tool_text(
        await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    )
    assert "Navigated to" in result
    assert "observation" not in result


async def test_navigate_observe_snapshot(client: Client, flask_server: str) -> None:
    result = tool_text(
        await client.call_tool(
            "navigate",
            {"url": f"{flask_server}/snapshot", "profile": PROFILE, "observe": "snapshot"},
        )
    )
    assert "Navigated to" in result
    assert "--- observation (snapshot) ---" in result
    _, _, block = result.partition("--- observation (snapshot) ---")
    assert re.search(r"e\d+", block), "snapshot observation must expose interactive uids"


async def test_navigate_observe_text(client: Client, flask_server: str) -> None:
    result = tool_text(
        await client.call_tool(
            "navigate",
            {"url": f"{flask_server}/snapshot", "profile": PROFILE, "observe": "text"},
        )
    )
    assert "Navigated to" in result
    assert "--- observation (text) ---" in result
    assert "Snapshot Test" in result  # page body innerText


async def test_navigate_observe_invalid(client: Client, flask_server: str) -> None:
    result = tool_text(
        await client.call_tool(
            "navigate",
            {"url": f"{flask_server}/click", "profile": PROFILE, "observe": "bogus"},
        )
    )
    assert "Error: ValueError:" in result
    assert "invalid observe" in result


async def test_navigate_observe_failure_is_nonfatal(
    client: Client, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing observation must not fail the tool: the action already succeeded.

    The navigation completes, then the snapshot capture is forced to raise. The
    result must still report the successful navigation plus a best-effort
    "[observation failed: ...]" note rather than surfacing as an error, so the model
    is never tempted to re-run the (already successful) navigation.
    """
    from camoufox_mcp.tools import _observe

    async def _boom(_page: object) -> str:
        raise RuntimeError("snapshot exploded")

    monkeypatch.setattr(_observe, "capture_snapshot", _boom)

    result = tool_text(
        await client.call_tool(
            "navigate",
            {"url": f"{flask_server}/click", "profile": PROFILE, "observe": "snapshot"},
        )
    )
    assert "Navigated to" in result
    assert "[observation failed:" in result
    assert "snapshot exploded" in result
