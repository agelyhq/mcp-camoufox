from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_DEFAULT_LIMIT = 50


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_console_messages(
        profile: str,
        levels: list[str] | None = None,
        limit: int = _DEFAULT_LIMIT,
        include_preserved: bool = False,
    ) -> str:
        """List console messages emitted by the active tab's page.

        Messages are captured chronologically by the per-tab console monitor. Each
        line shows the message id, level, source location and text. Useful for
        diagnosing JavaScript errors, warnings and page logging.

        Params:
        - profile: session/profile name (required). The session is created lazily.
        - levels: optional filter by console level, e.g. ["error", "warning",
          "log", "info", "debug"]. Case-insensitive.
        - limit: max number of most-recent matching messages to return
          (default 50).
        - include_preserved: also include messages captured before the last
          navigation (default False).

        Returns a text listing, or "No console messages captured." when empty.

        Errors: "Error: ProfileInUseError: ..." if the profile is locked;
        "Error: RuntimeError: ..." if there is no active page.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        entries = page.console.list_entries(
            levels=levels,
            limit=limit,
            include_preserved=include_preserved,
        )
        if not entries:
            return "No console messages captured."

        lines = []
        for e in entries:
            loc = f" ({e.url}:{e.line_number})" if e.url else ""
            lines.append(f"[{e.msgid}] {e.level.upper()}{loc}: {e.text}")
        return f"Console messages ({len(entries)}):\n" + "\n".join(lines)
