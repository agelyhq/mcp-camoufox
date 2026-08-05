from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions import format_status
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._text import truncate_chars

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_DEFAULT_MAX_BODY = 50000
_HEADER_LIMIT = 40
_RAISE_MAX_BODY = "Raise max_body_size to see more"


def _format_headers(headers: dict[str, str]) -> str:
    if not headers:
        return "  <none>"
    items = list(headers.items())[:_HEADER_LIMIT]
    text = "\n".join(f"  {name}: {value}" for name, value in items)
    if len(headers) > _HEADER_LIMIT:
        text += f"\n  ... ({len(headers) - _HEADER_LIMIT} more)"
    return text


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def get_network_request(
        profile: str,
        reqid: int,
        include_body: bool = True,
        max_body_size: int = _DEFAULT_MAX_BODY,
    ) -> str:
        """Full details of 1 captured request: headers, POST data and response body.

        Args:
            reqid: Request id from ``list_network_requests``.
            include_body: Bodies exist only for completed responses the browser still
                holds.
            max_body_size: Response-body characters before truncation.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        entry = page.network.get_entry(reqid)
        if entry is None:
            return f"No request found with id {reqid}."

        lines = [
            f"Request [{entry.reqid}] {entry.method} {entry.url}",
            f"Resource type: {entry.resource_type}",
            f"Status: {format_status(entry.status)}",
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
            body = await page.network.get_response_body(entry)
            rendered = (
                "<unavailable>"
                if body is None
                else truncate_chars(body, max_body_size, _RAISE_MAX_BODY)
            )
            lines += ["", "Response body:", rendered]

        return "\n".join(lines)
