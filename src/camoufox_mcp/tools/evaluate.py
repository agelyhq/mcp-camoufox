from __future__ import annotations

import json

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def evaluate(script: str, ctx: Context) -> str:
        """Execute JavaScript in the page context.

        Args:
            script: JS expression or IIFE. Must return JSON-serializable value.
        """
        try:
            page = get_page(ctx)
            result = await page.evaluate(script)
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2, ensure_ascii=False)
            return str(result) if result is not None else "(no return value)"
        except Exception as e:
            return f"JS Error: {type(e).__name__}: {e}"
