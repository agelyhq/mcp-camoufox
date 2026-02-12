from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_page_info(ctx: Context) -> str:
        """List all open browser tabs with their index, URL, title, and
        which tab is currently active.
        """
        try:
            manager = get_manager(ctx)
            lines = []
            for idx, page_info in sorted(manager.pages.items()):
                handle = page_info.handle
                active = " [ACTIVE]" if idx == manager.active_page_idx else ""
                title = await handle.get_title() or "(no title)"
                lines.append(f"  [{idx}]{active} {title} | {handle.url}")

            return f"Open pages ({len(manager.pages)}):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
