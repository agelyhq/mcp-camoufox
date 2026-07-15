from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Client

from tests.helpers import tool_text

if TYPE_CHECKING:
    from fastmcp import FastMCP

COOKIE_JS = "document.getElementById('session-id').textContent"


async def _session_id(client: Client, url: str, profile: str) -> str:
    """Navigate with a profile and return the persisted session-id value."""
    await client.call_tool("navigate", {"url": url, "profile": profile})
    return tool_text(await client.call_tool("evaluate", {"profile": profile, "script": COOKIE_JS}))


async def test_profile_persistence(mcp_server: FastMCP, flask_server: str) -> None:
    """Closing and reopening the same profile must preserve its cookie."""
    url = f"{flask_server}/profile"

    async with Client(mcp_server) as c:
        sid1 = await _session_id(c, url, "persist_a")
        assert sid1, "Expected a non-empty session ID"
        await c.call_tool("close_session", {"profile": "persist_a"})

    async with Client(mcp_server) as c:
        sid2 = await _session_id(c, url, "persist_a")

    assert sid1 == sid2, f"Cookie lost across sessions: {sid1!r} != {sid2!r}"


async def test_different_profile_different_cookie(mcp_server: FastMCP, flask_server: str) -> None:
    """Different profile names must yield independent cookie stores."""
    url = f"{flask_server}/profile"

    async with Client(mcp_server) as c:
        sid_a = await _session_id(c, url, "diff_a")
        sid_b = await _session_id(c, url, "diff_b")

    assert sid_a != sid_b, f"Different profiles share the same cookie: {sid_a!r}"


async def test_multiple_profiles_independent(mcp_server: FastMCP, flask_server: str) -> None:
    """Each named profile persists its own cookie independently across restarts."""
    url = f"{flask_server}/profile"

    async with Client(mcp_server) as c:
        sid_a1 = await _session_id(c, url, "multi_a")
        sid_b = await _session_id(c, url, "multi_b")
        await c.call_tool("close_session", {"profile": "multi_a"})

    async with Client(mcp_server) as c:
        sid_a2 = await _session_id(c, url, "multi_a")

    assert sid_a1 == sid_a2, f"Profile multi_a cookie changed: {sid_a1!r} != {sid_a2!r}"
    assert sid_a1 != sid_b, f"Profiles multi_a and multi_b share the same cookie: {sid_a1!r}"
