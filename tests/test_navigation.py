from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.helpers import (
    OBSERVATION_SNAPSHOT_MARK,
    OBSERVATION_TEXT_MARK,
    PROFILE,
    tool_text,
)

if TYPE_CHECKING:
    import pytest
    from fastmcp import Client


async def test_back_and_reload(client: Client, flask_server: str) -> None:
    """Going back moves the tab, so it reports the page; reloading stays put.

    Neither tool restates its own URL: the "[page]" line is the single carrier for
    where the tab is, so the same fact never appears in 2 shapes.
    """
    first = f"{flask_server}/click"
    second = f"{flask_server}/snapshot"

    await client.call_tool("navigate", {"url": first, "profile": PROFILE})
    await client.call_tool("navigate", {"url": second, "profile": PROFILE})

    back = tool_text(await client.call_tool("go_back", {"profile": PROFILE}))
    assert back == f"Went back to: Click Test\n[page] Click Test | {first}", back

    reloaded = tool_text(await client.call_tool("reload", {"profile": PROFILE}))
    assert reloaded == "Reloaded: Click Test", reloaded


async def test_go_back_no_history(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(await client.call_tool("go_back", {"profile": PROFILE}))
    assert "no previous page" in result.lower()


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
    assert OBSERVATION_SNAPSHOT_MARK in result
    _, _, block = result.partition(OBSERVATION_SNAPSHOT_MARK)
    assert re.search(r"e\d+", block), "snapshot observation must expose interactive uids"


async def test_navigate_observe_text(client: Client, flask_server: str) -> None:
    result = tool_text(
        await client.call_tool(
            "navigate",
            {"url": f"{flask_server}/snapshot", "profile": PROFILE, "observe": "text"},
        )
    )
    assert "Navigated to" in result
    assert OBSERVATION_TEXT_MARK in result
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
