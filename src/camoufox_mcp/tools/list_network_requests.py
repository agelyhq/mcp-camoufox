from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions import format_status
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.sessions import NetworkEntry
    from camoufox_mcp.tools._base import ToolDeps

_DEFAULT_PAGE_SIZE = 50


def _format_entry(entry: NetworkEntry) -> str:
    return (
        f"[{entry.reqid}] {entry.method} {format_status(entry.status)} "
        f"{entry.resource_type} {entry.url}"
    )


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_network_requests(
        profile: str,
        resource_types: list[str] | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        page_idx: int = 0,
        include_preserved: bool = False,
    ) -> str:
        """List HTTP requests captured on the active tab, in chronological order.

        Each line carries the request id for ``get_network_request``, the method,
        status, resource type and URL. Status "pending" means no response has arrived,
        "failed" means the request errored.

        Args:
            resource_types: Filter, e.g. ["document", "xhr", "fetch", "script",
                "stylesheet", "image", "font"]. Case-insensitive.
            page_size: Entries per page.
            page_idx: Zero-based page index into the filtered set.
            include_preserved: Also include requests from before the last navigation.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        entries, total = page.network.list_entries(
            resource_types=resource_types,
            page_size=page_size,
            page_idx=page_idx,
            include_preserved=include_preserved,
        )
        if total == 0:
            return "No network requests captured."

        lines = [_format_entry(entry) for entry in entries]
        shown = len(entries)
        first = page_idx * page_size
        header = (
            f"Network requests {first + 1}-{first + shown} of {total} "
            f"(page {page_idx}, page_size {page_size}):"
        )
        return header + "\n" + "\n".join(lines)
