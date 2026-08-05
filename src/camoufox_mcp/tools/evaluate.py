from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom import evaluate_with_uids
from camoufox_mcp.telemetry_intent import evaluate_analytics
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._text import render_capped

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def _analytics(args: dict[str, Any]) -> dict[str, Any]:
    """What a call to this tool is worth measuring beyond the shared record.

    Declared here, next to the tool it describes, so the generic wrapper never has to
    name a tool: the script's intent bucket and its literal-stripped fingerprint are
    what turn 8,795 evaluate calls into an answer about what agents use them for.
    """
    script = args.get("script")
    return evaluate_analytics(script) if isinstance(script, str) else {}


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps, analytics=_analytics)
    async def evaluate(
        profile: str,
        script: str,
        uids: list[str] | None = None,
        max_chars: int = 20000,
        max_items: int = 200,
    ) -> str:
        """Run a JavaScript expression in the active tab and return its JSON result.

        Args:
            script: ONE expression, not statements: ``"document.title"``,
                ``"(() => { ... })()"``. A lone function value is auto-invoked.
                Top-level ``await`` is a SyntaxError, so use an async IIFE
                (``"(async () => (await fetch('/x')).json())()"``) or return the
                promise, which is awaited. The value must be JSON-serializable, so
                return a node's property rather than the node.
            uids: Snapshot uids handed to the script as live elements. ``script`` must
                then be a function expression taking 1 argument per uid, e.g.
                ``uids=["e3", "e7"]`` with ``"(a, b) => a.id + b.id"``.
            max_chars: Cap on the returned text (``<= 0`` unlimited).
            max_items: Array results only (``<= 0`` unlimited). An array is cut at an
                element boundary, so a truncated result still parses as JSON.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        if uids:
            return render_capped(await evaluate_with_uids(page, script, uids), max_chars, max_items)
        return render_capped(await page.evaluate(script), max_chars, max_items)
