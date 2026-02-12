from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.dom import get_snapshot_js
from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def take_snapshot(ctx: Context) -> str:
        """Capture a text representation of the current page.

        Returns an ARIA-inspired structured tree built from the live DOM.
        Visible structural elements (headings, lists, tables, landmarks) and
        interactive elements (links, buttons, inputs, ARIA roles) are included.
        Interactive elements are tagged with UIDs (e.g., e0, e1) that can be
        used with click, fill, and other interaction tools.

        MUST be called before using click/fill to obtain valid UIDs.
        Call again after any interaction or navigation to refresh state."""
        try:
            page = get_page(ctx)
            result = await page.evaluate(get_snapshot_js())
            if isinstance(result, dict):
                return result.get("tree", str(result))
            return str(result)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
