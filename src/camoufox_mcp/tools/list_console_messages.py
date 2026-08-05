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
        """List console messages from the active tab, in chronological order.

        Each line carries the message id, level, source location and text.

        Args:
            levels: Filter, e.g. ["error", "warning", "log", "info", "debug"].
                Case-insensitive.
            limit: Most-recent matching messages returned.
            include_preserved: Also include messages from before the last navigation.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        matched, _ = page.console.list_entries(levels=levels, include_preserved=include_preserved)
        # The tail, not a page: a console is read for what just happened, so the
        # newest messages are the ones worth the tokens. The monitor pages like the
        # network one; which end of the match to keep is this tool's own policy.
        entries = matched[-limit:] if limit > 0 else matched
        if not entries:
            return "No console messages captured."

        lines = []
        for entry in entries:
            location = f" ({entry.url}:{entry.line_number})" if entry.url else ""
            lines.append(f"[{entry.msgid}] {entry.level.upper()}{location}: {entry.text}")
        return f"Console messages ({len(entries)}):\n" + "\n".join(lines)
