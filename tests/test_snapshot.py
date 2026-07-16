from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def _snapshot(client: Client, **kwargs: object) -> str:
    return tool_text(await client.call_tool("snapshot", {"profile": PROFILE, **kwargs}))


async def test_snapshot_returns_tree(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})

    snap = await _snapshot(client)
    # Count the eNN UIDs instead of substring-matching "e0"/"e1" (which also
    # matches "e10", "e11", ...). The rich snapshot page has many UIDs.
    assert len(re.findall(r"e\d+", snap)) >= 5
    assert "heading" in snap.lower() or "button" in snap.lower() or "link" in snap.lower()


async def test_snapshot_contains_uids(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    snap = await _snapshot(client)
    assert "Click me" in snap
    assert "Double-click" in snap

    uids = re.findall(r"e\d+", snap)
    assert len(uids) >= 3


async def test_snapshot_lazily_creates_session(client: Client, flask_server: str) -> None:
    """`snapshot` on an unused profile launches the session on a blank page."""
    snap = tool_text(await client.call_tool("snapshot", {"profile": "fresh_snap"}))
    assert "error" not in snap.lower()


async def test_snapshot_max_nodes_truncates(client: Client, flask_server: str) -> None:
    """A DOM larger than max_nodes is capped and reports the overflow count."""
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})
    await evaluate(
        client,
        PROFILE,
        "(() => { const p = []; for (let i = 0; i < 2000; i++) "
        "{ p.push('<button>Btn ' + i + '</button>'); } "
        "document.body.innerHTML = p.join(''); return p.length; })()",
    )

    snap = await _snapshot(client)  # default max_nodes=1500

    assert "[truncated: 500 more nodes" in snap
    assert "interactive_only=true" in snap
    uids = re.findall(r"e\d+", snap)
    assert len(uids) == 1500
    assert "e1499" in snap
    assert "e1500" not in snap


async def test_snapshot_max_nodes_raise_shows_all(client: Client, flask_server: str) -> None:
    """Raising max_nodes above the node count renders the whole tree, no note."""
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})
    await evaluate(
        client,
        PROFILE,
        "(() => { const p = []; for (let i = 0; i < 2000; i++) "
        "{ p.push('<button>Btn ' + i + '</button>'); } "
        "document.body.innerHTML = p.join(''); return p.length; })()",
    )

    snap = await _snapshot(client, max_nodes=2500)

    assert "truncated" not in snap
    assert len(re.findall(r"e\d+", snap)) == 2000
    assert "e1999" in snap


async def test_snapshot_interactive_only_drops_structural(
    client: Client, flask_server: str
) -> None:
    """interactive_only removes structural leaves but keeps every uid intact."""
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})
    await evaluate(
        client,
        PROFILE,
        "(() => { const p = []; for (let i = 0; i < 40; i++) "
        "{ p.push('<p>Paragraph ' + i + '</p>'); } "
        "for (let i = 0; i < 5; i++) { p.push('<button>Action ' + i + '</button>'); } "
        "document.body.innerHTML = p.join(''); return p.length; })()",
    )

    full = await _snapshot(client)
    assert full.count("Paragraph") == 40
    assert "Action 0" in full

    lean = await _snapshot(client, interactive_only=True)
    assert "Paragraph" not in lean
    assert "Action 0" in lean
    assert len(re.findall(r"e\d+", lean)) == 5
    # The button uids are the same interactive elements in both renderings.
    assert extract_uid(full, "Action 0") == extract_uid(lean, "Action 0")


async def test_snapshot_interactive_only_keeps_ancestors(client: Client, flask_server: str) -> None:
    """A structural ancestor of an interactive element survives interactive_only."""
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})
    await evaluate(
        client,
        PROFILE,
        "(() => { document.body.innerHTML = "
        "'<p>lonely para</p><form><label>Full name</label>"
        '<input type="text" name="fn"></form>\'; return 1; })()',
    )

    lean = await _snapshot(client, interactive_only=True)

    assert "lonely para" not in lean  # structural leaf dropped
    assert "form" in lean  # interactive ancestor kept for context
    assert "input:text" in lean
