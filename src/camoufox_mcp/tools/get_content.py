from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_content(ctx: Context, outer_html: bool = False) -> str:
        """Get the HTML content of the active page.

        Args:
            outer_html: If true, return full document HTML including <head>.
                        Default: body innerHTML only.
        """
        try:
            page = get_page(ctx)
            if outer_html:
                return await page.evaluate("document.documentElement.outerHTML")
            return await page.evaluate("document.body.innerHTML")
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
