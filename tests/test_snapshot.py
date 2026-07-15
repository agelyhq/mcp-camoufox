from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_snapshot_returns_tree(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})

    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    # Count the eNN UIDs instead of substring-matching "e0"/"e1" (which also
    # matches "e10", "e11", ...). The rich snapshot page has many UIDs.
    assert len(re.findall(r"e\d+", snap)) >= 5
    assert "heading" in snap.lower() or "button" in snap.lower() or "link" in snap.lower()


async def test_snapshot_contains_uids(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    assert "Click me" in snap
    assert "Double-click" in snap

    uids = re.findall(r"e\d+", snap)
    assert len(uids) >= 3


async def test_snapshot_lazily_creates_session(client: Client, flask_server: str) -> None:
    """`snapshot` on an unused profile launches the session on a blank page."""
    snap = tool_text(await client.call_tool("snapshot", {"profile": "fresh_snap"}))
    assert "error" not in snap.lower()
