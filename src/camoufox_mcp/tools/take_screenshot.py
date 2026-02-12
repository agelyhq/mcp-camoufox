from __future__ import annotations

import base64

from fastmcp import Context, FastMCP  # noqa: TC002
from mcp.types import ImageContent, TextContent

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def take_screenshot(ctx: Context, full_page: bool = False) -> list:
        """Take a screenshot of the active page.

        Args:
            full_page: Capture entire scrollable page (default: viewport only)
        """
        try:
            page = get_page(ctx)
            png_bytes = await page.screenshot(full_page=full_page)
            return [
                ImageContent(
                    type="image",
                    data=base64.b64encode(png_bytes).decode(),
                    mimeType="image/png",
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]
