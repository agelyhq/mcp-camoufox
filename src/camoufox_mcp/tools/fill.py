from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.dom import clear_field, resolve_uid, scroll_into_view, uid_selector
from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def fill(uid: str, value: str, ctx: Context, clear_first: bool = True) -> str:
        """Fill a text input, textarea, or contenteditable element.

        Args:
            uid: Element UID from take_snapshot
            value: Text to enter
            clear_first: Clear existing content before typing (default: true)
        """
        try:
            page = get_page(ctx)
            info = await resolve_uid(page, uid)
            if "error" in info:
                return f"Error: {info['error']}"
            if not info.get("editable"):
                return f"Error: Element {uid} ({info['tag']}) is not editable"

            truncated = value[:50] + ("..." if len(value) > 50 else "")

            if info["tag"] == "select":
                await page.select_option(uid_selector(uid), value)
                return f"Filled {info['tag']} ({uid}) with: {truncated}"

            await scroll_into_view(page, uid)
            info = await resolve_uid(page, uid)
            if "error" in info:
                return f"Error: {info['error']}"

            await page.click_at(info["x"], info["y"])

            if clear_first:
                result = await clear_field(page, uid)
                if "error" in result:
                    return f"Error: {result['error']}"

            await page.insert_text(value)
            return f"Filled {info['tag']} ({uid}) with: {truncated}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
