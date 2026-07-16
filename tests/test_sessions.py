from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Client

from tests.helpers import evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import FastMCP

PROFILE_A = "sess_a"
PROFILE_B = "sess_b"

SET_STATE_JS = (
    "localStorage.setItem('shared', 'A-value');"
    "document.cookie = 'who=cookieA; path=/';"
    "localStorage.getItem('shared')"
)


async def test_two_profiles_are_isolated(client: Client, flask_server: str) -> None:
    """State written in profile A must be invisible to a concurrent profile B."""
    url = f"{flask_server}/"

    await client.call_tool("navigate", {"url": url, "profile": PROFILE_A})
    written = await evaluate(client, PROFILE_A, SET_STATE_JS)
    assert "A-value" in written

    await client.call_tool("navigate", {"url": url, "profile": PROFILE_B})
    b_local = await evaluate(client, PROFILE_B, "localStorage.getItem('shared')")
    b_cookie = await evaluate(client, PROFILE_B, "document.cookie")
    assert b_local == "null", f"localStorage leaked into profile B: {b_local!r}"
    assert "cookieA" not in b_cookie, f"cookie leaked into profile B: {b_cookie!r}"

    # Profile A must still hold its own state while B is live.
    a_local = await evaluate(client, PROFILE_A, "localStorage.getItem('shared')")
    assert "A-value" in a_local


async def test_list_sessions_reflects_state(client: Client, flask_server: str) -> None:
    url = f"{flask_server}/"
    await client.call_tool("navigate", {"url": url, "profile": PROFILE_A})
    await client.call_tool("navigate", {"url": url, "profile": PROFILE_B})

    listing = tool_text(await client.call_tool("list_sessions", {}))
    assert PROFILE_A in listing
    assert PROFILE_B in listing

    closed = tool_text(await client.call_tool("close_session", {"profile": PROFILE_B}))
    assert "closed" in closed.lower()

    listing2 = tool_text(await client.call_tool("list_sessions", {}))
    assert PROFILE_A in listing2
    assert PROFILE_B not in listing2


async def test_close_session_idempotent(client: Client) -> None:
    result = tool_text(await client.call_tool("close_session", {"profile": "never_opened"}))
    assert "no active session" in result.lower()


async def test_close_then_reopen_reuses_cookies(mcp_server: FastMCP, flask_server: str) -> None:
    """After close_session, re-navigating the same profile reuses persisted cookies."""
    url = f"{flask_server}/"
    profile = "persist_reuse"

    async with Client(mcp_server) as c:
        await c.call_tool("navigate", {"url": url, "profile": profile})
        await evaluate(
            c,
            profile,
            "document.cookie = 'pc=persist42; path=/; max-age=31536000'; document.cookie",
        )
        await c.call_tool("close_session", {"profile": profile})

        await c.call_tool("navigate", {"url": url, "profile": profile})
        cookie = await evaluate(c, profile, "document.cookie")

    assert "persist42" in cookie, f"cookie not persisted across restart: {cookie!r}"
