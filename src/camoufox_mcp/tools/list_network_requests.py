from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_network_requests(
        ctx: Context,
        resource_types: list[str] | None = None,
        page_size: int | None = None,
        page_idx: int = 0,
        include_preserved: bool = False,
    ) -> str:
        """List captured network requests for the active page since the last navigation.

        Args:
            resource_types: Filter by resource type (e.g. xhr, fetch, document, script).
                           When omitted, returns all types.
            page_size: Max number of requests to return. Omit to return all.
            page_idx: Page number (0-based) for pagination.
            include_preserved: Include requests from previous navigations (up to 3).
        """
        try:
            page = get_page(ctx)
            entries, total = page.network.list_entries(
                resource_types=resource_types,
                page_size=page_size,
                page_idx=page_idx,
                include_preserved=include_preserved,
            )

            if not entries:
                return "No network requests captured."

            lines = [f"Network requests ({len(entries)}/{total} total):"]
            lines.append(f"{'reqid':>5}  {'method':<7} {'status':>6}  {'type':<10} url")
            lines.append("-" * 80)
            for e in entries:
                status = str(e.status) if e.status is not None else "..."
                lines.append(
                    f"{e.reqid:>5}  {e.method:<7} {status:>6}  {e.resource_type:<10} {e.url}"
                )

            return "\n".join(lines)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
