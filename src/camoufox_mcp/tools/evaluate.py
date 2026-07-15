from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def evaluate(profile: str, script: str) -> str:
        """Evaluate a JavaScript expression in the active tab's page context.

        Runs arbitrary JS against the live page and returns its result. The script
        must be a single JS expression or an IIFE — for example
        ``"document.title"``, ``"window.location.href"``, or
        ``"(() => { return [...document.links].length })()"``. Async expressions
        (returning a Promise) are awaited automatically.

        The return value must be JSON-serializable; DOM nodes and functions cannot
        be returned directly — extract primitives/arrays/objects instead.

        Params:
            profile: The browser profile whose active tab runs the script.
            script: A JavaScript expression (or IIFE) evaluated in page context.

        Returns:
            The JSON-serialized result. Values that are not JSON-serializable are
            rendered with a string fallback. ``undefined``/``null`` return "null".

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: Error: ..." for JS runtime/syntax errors thrown by the page.
            - "Error: ProfileInUseError: ..." if the profile lock is held.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        result: Any = await page.evaluate(script)
        try:
            return json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(str(result), ensure_ascii=False)
