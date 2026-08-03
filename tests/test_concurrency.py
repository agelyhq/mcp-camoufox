from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

PROFILE_A = "conc_a"
PROFILE_B = "conc_b"
PROFILE_SHARED = "conc_shared"


async def test_parallel_profiles_full_lifecycle(client: Client, flask_server: str) -> None:
    """Two profiles created, driven and closed through truly simultaneous calls.

    Unlike test_sessions.py (sequential awaits on coexisting sessions), every step
    here runs both profiles at the same instant via asyncio.gather.
    """
    url = f"{flask_server}/"

    nav_a, nav_b = await asyncio.gather(
        client.call_tool("navigate", {"url": url, "profile": PROFILE_A}),
        client.call_tool("navigate", {"url": url, "profile": PROFILE_B}),
    )
    assert tool_text(nav_a).startswith("Navigated to:"), tool_text(nav_a)
    assert tool_text(nav_b).startswith("Navigated to:"), tool_text(nav_b)

    await asyncio.gather(
        evaluate(client, PROFILE_A, "localStorage.setItem('mark', 'from-A')"),
        evaluate(client, PROFILE_B, "localStorage.setItem('mark', 'from-B')"),
    )
    mark_a, mark_b = await asyncio.gather(
        evaluate(client, PROFILE_A, "localStorage.getItem('mark')"),
        evaluate(client, PROFILE_B, "localStorage.getItem('mark')"),
    )
    assert "from-A" in mark_a and "from-B" not in mark_a, f"profile A saw {mark_a!r}"
    assert "from-B" in mark_b and "from-A" not in mark_b, f"profile B saw {mark_b!r}"

    listing = tool_text(await client.call_tool("list_sessions", {}))
    assert f"Session '{PROFILE_A}'" in listing
    assert f"Session '{PROFILE_B}'" in listing

    closed_a, closed_b = await asyncio.gather(
        client.call_tool("close_session", {"profile": PROFILE_A}),
        client.call_tool("close_session", {"profile": PROFILE_B}),
    )
    assert "closed" in tool_text(closed_a).lower()
    assert "closed" in tool_text(closed_b).lower()
    assert tool_text(await client.call_tool("list_sessions", {})) == "No active sessions."


async def test_parallel_first_calls_same_profile_share_one_session(
    client: Client, flask_server: str
) -> None:
    """Simultaneous first calls on one profile must converge on a single session."""
    url = f"{flask_server}/"

    results = await asyncio.gather(
        client.call_tool("navigate", {"url": url, "profile": PROFILE_SHARED}),
        client.call_tool("navigate", {"url": url, "profile": PROFILE_SHARED}),
    )
    texts = [tool_text(r) for r in results]

    # The two goto calls race on the same tab, so one may report an interrupted
    # navigation — but at least one must land, exactly one session may exist, and
    # the session must stay usable afterwards.
    assert any(t.startswith("Navigated to:") for t in texts), texts

    listing = tool_text(await client.call_tool("list_sessions", {}))
    assert listing.count(f"Session '{PROFILE_SHARED}'") == 1

    title = await evaluate(client, PROFILE_SHARED, "document.title")
    assert not title.startswith(("Error:", "Timeout:")), title
