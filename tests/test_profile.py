from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastmcp import Client

from tests.helpers import evaluate

if TYPE_CHECKING:
    from fastmcp import FastMCP

COOKIE_JS = "document.getElementById('session-id').textContent"

# The cookie the page mints is a v4 UUID, and ``evaluate`` renders a string result as
# JSON, so this is the whole output when the read worked. Matching it is what makes
# every comparison below about a cookie: ``evaluate`` renders a read of nothing as the
# 2-character string '""' and a failed call as an "Error: ..." line, both truthy and
# both equal to themselves, so "assert sid" was satisfied by a page whose script never
# ran and by a tool call that never reached the page, and the persistence comparison
# was then satisfied by 2 identical non-answers.
_RENDERED_SESSION_ID = re.compile(
    r'^"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"$'
)


async def _session_id(client: Client, url: str, profile: str) -> str:
    """Navigate with a profile and return the session id the page persisted.

    The shape is checked here rather than in one test, because every assertion in this
    file compares 2 of these values and none of them can tell a cookie from a pair of
    matching failures.
    """
    await client.call_tool("navigate", {"url": url, "profile": profile})
    raw = await evaluate(client, profile, COOKIE_JS)
    assert _RENDERED_SESSION_ID.match(raw), f"not a session id the page minted: {raw!r}"
    return raw


async def test_profile_persistence(mcp_server: FastMCP, flask_server: str) -> None:
    """Closing and reopening the same profile must preserve its cookie."""
    url = f"{flask_server}/profile"

    async with Client(mcp_server) as c:
        sid1 = await _session_id(c, url, "persist_a")
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
