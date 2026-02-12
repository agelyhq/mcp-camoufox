from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_console_messages(
        ctx: Context,
        levels: list[str] | None = None,
        limit: int = 50,
        include_preserved: bool = False,
    ) -> str:
        """List captured browser console messages for the active page.

        Useful for debugging — shows errors, warnings, and log output from the page.

        Args:
            levels: Filter by level (e.g. error, warning, log, info, debug).
                   When omitted, returns all levels.
            limit: Max number of messages to return (default: 50, most recent).
            include_preserved: Include messages from previous navigations.
        """
        try:
            page = get_page(ctx)
            entries = page.console.list_entries(
                levels=levels,
                limit=limit,
                include_preserved=include_preserved,
            )

            if not entries:
                return "No console messages captured."

            lines = [f"Console messages ({len(entries)}):"]
            lines.append(f"{'msgid':>5}  {'level':<8} message")
            lines.append("-" * 80)
            for e in entries:
                location = f" ({e.url}:{e.line_number})" if e.url else ""
                lines.append(f"{e.msgid:>5}  {e.level:<8} {e.text}{location}")

            return "\n".join(lines)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
