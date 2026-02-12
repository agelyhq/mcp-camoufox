from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_profiles(ctx: Context) -> str:
        """List all available browser profiles.

        Returns the names of profile directories found under the configured
        CAMOUFOX_PROFILES_DIR. Returns an error if the directory is not set.
        """
        try:
            manager = get_manager(ctx)
            profiles_dir = manager.config.profiles_dir
            if not profiles_dir:
                return "Error: CAMOUFOX_PROFILES_DIR is not configured."
            path = Path(profiles_dir)
            if not path.is_dir():
                return "No profiles found (directory does not exist)."
            names = sorted(d.name for d in path.iterdir() if d.is_dir())
            if not names:
                return "No profiles found."
            return "\n".join(names)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
