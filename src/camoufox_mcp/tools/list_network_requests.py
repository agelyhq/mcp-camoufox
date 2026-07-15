from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions import format_status
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.sessions import NetworkEntry
    from camoufox_mcp.tools._base import ToolDeps

_DEFAULT_PAGE_SIZE = 50


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def list_network_requests(
        profile: str,
        resource_types: list[str] | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        page_idx: int = 0,
        include_preserved: bool = False,
    ) -> str:
        """List HTTP requests captured on the active tab, most-recent order preserved.

        Requests are recorded chronologically by the per-tab network monitor. Each
        line shows the request id (use it with ``get_network_request`` to fetch the
        response body), method, status, resource type and URL. A status of
        ``pending`` means no response has arrived yet; ``failed`` means the request
        errored.

        Params:
        - profile: session/profile name (required). The session is created lazily
          if it does not exist yet.
        - resource_types: optional filter, e.g. ["document", "xhr", "fetch",
          "script", "stylesheet", "image", "font"]. Case-insensitive.
        - page_size: max entries per page (default 50).
        - page_idx: zero-based page index into the filtered result set.
        - include_preserved: also include requests captured before the last
          navigation (default False).

        Returns a text listing plus a summary line with the total match count and
        pagination info. Returns "No network requests captured." when empty.

        Errors: "Error: ProfileInUseError: ..." if the profile is locked by another
        process; "Error: RuntimeError: ..." if the session has no active page.
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

        lines = [_format_entry(e) for e in entries]
        shown = len(entries)
        first = page_idx * page_size
        header = (
            f"Network requests {first + 1}-{first + shown} of {total} "
            f"(page {page_idx}, page_size {page_size}):"
        )
        return header + "\n" + "\n".join(lines)

    def _format_entry(e: NetworkEntry) -> str:
        return f"[{e.reqid}] {e.method} {format_status(e.status)} {e.resource_type} {e.url}"
