from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._text import render_json

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def evaluate(profile: str, script: str) -> str:
        """Evaluate a JavaScript expression in the active tab's page context.

        Runs arbitrary JS against the live page and returns its result. The script
        is a single JS expression (NOT a sequence of statements) — for example
        ``"document.title"``, ``"window.location.href"``, or
        ``"(() => { return [...document.links].length })()"``.

        Async / awaiting (IMPORTANT — the return value is awaited if it is a
        Promise, but the script itself is NOT a module, so a bare top-level
        ``await`` is a SyntaxError). Use one of these forms instead:
            - async IIFE (recommended for multi-step logic):
              ``"(async () => { const r = await fetch('/api/data'); return r.json(); })()"``
            - bare Promise expression (awaited automatically):
              ``"fetch('/api/data').then(r => r.json())"``
            - a lone arrow/function value is auto-invoked, so this also works:
              ``"async () => (await fetch('/api/data')).json()"``
        WRONG — ``"await fetch('/api/data')"`` fails with
        "await is only valid in async functions ...". Wrap it in an async IIFE.

        The return value must be JSON-serializable; DOM nodes and functions cannot
        be returned directly — extract primitives/arrays/objects instead.

        Params:
            profile: The browser profile whose active tab runs the script.
            script: A JavaScript expression evaluated in page context (see the
                async forms above for anything that needs ``await``).

        Returns:
            The JSON-serialized result. Values that are not JSON-serializable are
            rendered with a string fallback. ``undefined``/``null`` return "null".

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: Error: ..." for JS runtime/syntax errors thrown by the page
              (including a bare top-level ``await``).
            - "Error: ProfileInUseError: ..." if the profile lock is held.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        result: Any = await page.evaluate(script)
        return render_json(result)
