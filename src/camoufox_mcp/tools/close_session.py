from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def close_session(profile: str) -> str:
        """Close the live browser for a profile and release its lock.

        Shuts down the Camoufox browser, all its tabs and per-tab monitors for the
        named profile, and releases the cross-process profile lock. The persistent
        on-disk profile directory (cookies, storage, fingerprint) is KEPT so a
        later ``navigate`` or other tool can reopen it. This operation is
        idempotent: closing a profile that is not active succeeds quietly.

        Params:
        - profile: session/profile name to close (required).

        Returns a confirmation string.

        Errors: exceptions are rendered as "Error: <Type>: <message>".
        """
        was_active = deps.sessions.get(profile) is not None
        await deps.sessions.close_session(profile)
        if was_active:
            return f"Closed session '{profile}' (profile data preserved on disk)."
        return f"No active session for '{profile}'; nothing to close."
