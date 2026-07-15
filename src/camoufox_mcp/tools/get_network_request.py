from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions import format_status
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_DEFAULT_MAX_BODY = 50000
_HEADER_LIMIT = 40


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def get_network_request(
        profile: str,
        reqid: int,
        include_body: bool = True,
        max_body_size: int = _DEFAULT_MAX_BODY,
    ) -> str:
        """Get full details for one captured network request by its id.

        Use ``list_network_requests`` first to discover request ids. Returns the
        method, URL, resource type, status, request/response headers, POST data (if
        any) and, when available, the response body (truncated past
        ``max_body_size``).

        Params:
        - profile: session/profile name (required).
        - reqid: the numeric request id from ``list_network_requests`` (required).
        - include_body: fetch and include the response body (default True). Bodies
          are only available for completed responses still held by the browser.
        - max_body_size: max response-body characters before truncation
          (default 50000).

        Returns a formatted text report, or "No request found with id <reqid>." if
        the id is unknown or has been evicted from the buffer.

        Errors: "Error: ProfileInUseError: ..." if the profile is locked;
        "Error: RuntimeError: ..." if there is no active page.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        entry = page.network.get_entry(reqid)
        if entry is None:
            return f"No request found with id {reqid}."

        status = format_status(entry.status)

        lines = [
            f"Request [{entry.reqid}] {entry.method} {entry.url}",
            f"Resource type: {entry.resource_type}",
            f"Status: {status}",
            "",
            "Request headers:",
            _format_headers(entry.request_headers),
        ]
        if entry.post_data:
            lines += ["", "POST data:", entry.post_data]
        lines += [
            "",
            "Response headers:",
            _format_headers(entry.response_headers or {}),
        ]

        if include_body:
            body = await page.network.get_response_body(entry, max_size=max_body_size)
            lines += ["", "Response body:", body if body is not None else "<unavailable>"]

        return "\n".join(lines)

    def _format_headers(headers: dict[str, str]) -> str:
        if not headers:
            return "  <none>"
        items = list(headers.items())[:_HEADER_LIMIT]
        text = "\n".join(f"  {k}: {v}" for k, v in items)
        if len(headers) > _HEADER_LIMIT:
            text += f"\n  ... ({len(headers) - _HEADER_LIMIT} more)"
        return text
