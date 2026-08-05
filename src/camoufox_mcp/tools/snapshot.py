from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import DEFAULT_INTERACTIVE_ONLY, DEFAULT_MAX_NODES, capture_snapshot
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def snapshot(
        profile: str,
        max_nodes: int = DEFAULT_MAX_NODES,
        interactive_only: bool = DEFAULT_INTERACTIVE_ONLY,
    ) -> str:
        """Capture the uid tree of the active tab's visible DOM, 1 line per element.

        Covers the top document only: iframe and shadow-root content is absent.

        Args:
            max_nodes: Cap on rendered nodes. Whole trailing nodes are dropped, never
                a partial line. 0 disables the cap.
            interactive_only: Keep only what can be clicked or typed into plus the
                ancestors that place it. False gives the whole structural tree.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        return await capture_snapshot(page, max_nodes=max_nodes, interactive_only=interactive_only)
