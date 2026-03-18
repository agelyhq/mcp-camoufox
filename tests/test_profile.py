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


async def test_multiple_profiles_independent(flask_server: str) -> None:
    """Different named profiles must each persist their own cookies independently."""
    url = f"{flask_server}/profile"

    async with Client(mcp) as c:
        sid_a1 = await _get_session_id(c, url, "multi_a")
        await c.call_tool("kill_session", {})

    async with Client(mcp) as c:
        sid_b = await _get_session_id(c, url, "multi_b")
        await c.call_tool("kill_session", {})

    async with Client(mcp) as c:
        sid_a2 = await _get_session_id(c, url, "multi_a")
        await c.call_tool("kill_session", {})

    assert sid_a1 == sid_a2, f"Profile multi_a cookie changed: {sid_a1!r} != {sid_a2!r}"
    assert sid_a1 != sid_b, f"Profiles multi_a and multi_b share the same cookie: {sid_a1!r}"
