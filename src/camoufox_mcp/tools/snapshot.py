from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import get_snapshot_js
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def snapshot(profile: str) -> str:
        """Capture an accessibility/UID text tree of the active tab.

        This is the primary primitive for driving a page: it walks the visible,
        interactive DOM and returns a compact indented text tree where every
        actionable element is tagged with a stable ``eN`` uid (e0, e1, ...). Those
        uids are what ``click``, ``type``, ``select``, ``upload`` and other
        interaction tools consume.

        Take a fresh snapshot after any navigation, reload, or DOM mutation: uids
        are only valid until the next navigation or the next snapshot, after which
        stale uids raise "unknown or stale uid; take a new snapshot".

        Params:
            profile: The browser profile whose active tab is snapshotted. The
                profile is launched lazily on first use.

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
        result = await page.evaluate(get_snapshot_js())
        if isinstance(result, dict):
            return str(result.get("tree", result))
        return str(result)
