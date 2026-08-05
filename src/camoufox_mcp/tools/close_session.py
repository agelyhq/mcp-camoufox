from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def close_session(profile: str) -> str:
        """Close the live browser for a profile and release its cross-process lock.

        Idempotent: closing an inactive profile succeeds quietly.
        """
        was_active = deps.sessions.get(profile) is not None
        await deps.sessions.close_session(profile)
        if was_active:
            return f"Closed session '{profile}' (profile data preserved on disk)."
        return f"No active session for '{profile}'; nothing to close."
