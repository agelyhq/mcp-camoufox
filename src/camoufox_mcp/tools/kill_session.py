from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def kill_session(ctx: Context) -> str:
        """Kill the running Camoufox browser and reset everything.

        Closes all pages, terminates the browser process, and releases resources.
        The next navigate call will start a fresh session.
        Safe to call even if no session is running.
        """
        try:
            manager = get_manager(ctx)
            if not manager.is_running:
                return "No session is running."
            await manager.stop_session()
            return "Session killed. Next navigate will start a new one."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
