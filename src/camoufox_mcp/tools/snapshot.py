from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import capture_snapshot
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def snapshot(profile: str, max_nodes: int = 1500, interactive_only: bool = False) -> str:
        """Capture a UID text tree of the active tab's visible DOM.

        This is the primary primitive for driving a page: it walks the visible DOM
        with ARIA-aware heuristics (roles, aria-label, ``<label for>``, focusability)
        and returns a compact indented text tree where every actionable element is
        tagged with an ``eN`` uid (e0, e1, ...). It is a DOM traversal rather than
        the browser's own accessibility tree, and it covers the top document only:
        iframe and shadow-root content is not visible to it. Those
        uids are what ``click``, ``type``, ``select``, ``upload`` and other
        interaction tools consume.

        Take a fresh snapshot after any navigation, reload, or DOM mutation: uids
        are only valid until the next navigation or the next snapshot, after which
        stale uids raise "unknown or stale uid; take a new snapshot".

        Params:
            profile: The browser profile whose active tab is snapshotted. The
                profile is launched lazily on first use.
            max_nodes: Cap on how many DOM nodes are rendered (default 1500). When
                the page has more, whole trailing nodes/subtrees are dropped (never
                a partial line) and a "[truncated: N more nodes ...]" note is
                appended; kept nodes keep the exact uids they would have uncapped.
                Raise it for a fuller tree, or set it to 0 to disable the cap.
            interactive_only: When true, render only interactive elements plus the
                minimal ancestor context that keeps the tree readable (structural
                leaves with no interactive descendant are dropped). Off by default
                because structural nodes are load-bearing for picking the right
                uid; turn it on to shrink large pages while keeping every uid.

        Returns:
            An indented text tree of interactive elements, each annotated with its
            ``eN`` uid, role/tag, and accessible name. Empty pages yield a minimal
            tree.

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: ProfileInUseError: ..." if another OS process holds the
              profile lock.
            - "Timeout: ..." if the page context is unavailable.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        return await capture_snapshot(page, max_nodes=max_nodes, interactive_only=interactive_only)
