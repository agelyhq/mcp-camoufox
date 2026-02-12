from __future__ import annotations

import json

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page

MAX_BODY_SIZE = 50000


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_network_request(
        reqid: int,
        ctx: Context,
        include_body: bool = True,
        max_body_size: int = MAX_BODY_SIZE,
    ) -> str:
        """Get full details of a network request by its reqid.

        Use list_network_requests first to find the reqid you need.

        Args:
            reqid: The request ID from list_network_requests.
            include_body: Whether to fetch the response body (default: true).
            max_body_size: Max response body chars to return (default: 50000).
        """
        try:
            page = get_page(ctx)
            entry = page.network.get_entry(reqid)
            if entry is None:
                return f"Error: No request found with reqid={reqid}"

            lines = [
                f"Request #{entry.reqid}",
                f"  URL: {entry.url}",
                f"  Method: {entry.method}",
                f"  Resource type: {entry.resource_type}",
                "",
                "Request headers:",
            ]
            for k, v in entry.request_headers.items():
                lines.append(f"  {k}: {v}")

            if entry.post_data:
                lines.append("")
                lines.append("Request body:")
                lines.append(_format_body(entry.post_data))

            lines.append("")
            if entry.status is None:
                lines.append("Response: pending")
            elif entry.status == 0:
                lines.append("Response: failed")
            else:
                lines.append(f"Response status: {entry.status}")

                if entry.response_headers:
                    lines.append("Response headers:")
                    for k, v in entry.response_headers.items():
                        lines.append(f"  {k}: {v}")

                if include_body:
                    body = await page.network.get_response_body(entry, max_size=max_body_size)
                    if body is not None:
                        lines.append("")
                        lines.append("Response body:")
                        lines.append(_format_body(body))
                    else:
                        lines.append("Response body: unavailable")

            return "\n".join(lines)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


def _format_body(body: str) -> str:
    try:
        parsed = json.loads(body)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return body
