from __future__ import annotations

from fastmcp import Client

from camoufox_mcp.server import mcp
from tests.helpers import tool_text

COOKIE_JS = "document.getElementById('session-id').textContent"


async def _get_session_id(client: Client, url: str, profile: str) -> str:
    """Navigate with a profile and return the session-id cookie value."""
    await client.call_tool("navigate", {"url": url, "profile": profile})
    return tool_text(await client.call_tool("evaluate", {"script": COOKIE_JS}))


async def test_profile_persistence(flask_server: str) -> None:
    """Same profile across sessions must preserve cookies."""
    url = f"{flask_server}/profile"

    async with Client(mcp) as c:
        sid1 = await _get_session_id(c, url, "persist_a")
        assert sid1, "Expected a non-empty session ID"
        await c.call_tool("kill_session", {})

    async with Client(mcp) as c:
        sid2 = await _get_session_id(c, url, "persist_a")
        await c.call_tool("kill_session", {})

    assert sid1 == sid2, f"Cookie lost across sessions: {sid1!r} != {sid2!r}"


async def test_different_profile_different_cookie(flask_server: str) -> None:
    """Different profile names must yield independent cookie stores."""
    url = f"{flask_server}/profile"

    async with Client(mcp) as c:
        sid_a = await _get_session_id(c, url, "diff_a")
        await c.call_tool("kill_session", {})

    async with Client(mcp) as c:
        sid_b = await _get_session_id(c, url, "diff_b")
        await c.call_tool("kill_session", {})

    assert sid_a != sid_b, f"Different profiles share the same cookie: {sid_a!r}"


async def test_list_profiles(flask_server: str) -> None:
    """list_profiles returns created profile names after sessions."""
    url = f"{flask_server}/profile"

    async with Client(mcp) as c:
        await _get_session_id(c, url, "list_a")
        profiles_after = tool_text(await c.call_tool("list_profiles", {}))
        assert "list_a" in profiles_after, f"Expected 'list_a' in {profiles_after!r}"
        await c.call_tool("kill_session", {})

    async with Client(mcp) as c:
        await _get_session_id(c, url, "list_b")
        await c.call_tool("kill_session", {})

    async with Client(mcp) as c:
        profiles = tool_text(await c.call_tool("list_profiles", {}))
        names = profiles.strip().splitlines()
        assert "list_a" in names, f"Expected 'list_a' in {names}"
        assert "list_b" in names, f"Expected 'list_b' in {names}"
