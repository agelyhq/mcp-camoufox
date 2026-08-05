from __future__ import annotations

import json
from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._errors import validate_choice
from camoufox_mcp.tools._text import truncate_chars

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_VALID_MODES = ("html", "text")


def _build_extract_js(selector: str | None, mode: str, strip_scripts: bool) -> str:
    """Build the IIFE that scopes, optionally strips scripts, and serializes.

    ``selector``/``mode``/``strip_scripts`` are embedded as JSON literals so any
    quotes in the selector are safely escaped. The IIFE returns ``{matched, value}``:
    ``matched`` is ``false`` when a selector matched nothing, otherwise ``value``
    holds the requested outerHTML/innerText. In html mode the scope is cloned before
    scripts are removed, so the live page is never mutated.
    """
    return (
        "(function() {"
        f"  const selector = {json.dumps(selector)};"
        f"  const mode = {json.dumps(mode)};"
        f"  const stripScripts = {json.dumps(strip_scripts)};"
        "  const scope = selector === null"
        "    ? document.documentElement"
        "    : document.querySelector(selector);"
        "  if (scope === null) { return { matched: false }; }"
        '  if (mode === "text") {'
        '    return { matched: true, value: scope.innerText || "" };'
        "  }"
        "  let node = scope;"
        "  if (stripScripts) {"
        "    node = scope.cloneNode(true);"
        '    node.querySelectorAll("script").forEach((s) => s.remove());'
        "  }"
        "  return { matched: true, value: node.outerHTML };"
        "})()"
    )


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def get_html(
        profile: str,
        selector: str | None = None,
        max_chars: int = 20000,
        strip_scripts: bool = True,
        mode: str = "html",
    ) -> str:
        """Read markup or visible text from the active tab, scoped and capped.

        Reflects the live post-JavaScript DOM, not the network response.
        ``mode="text"`` with a ``selector`` is the cheap way to read page content.

        Args:
            selector: Scopes the output to the FIRST match; the whole document when
                omitted.
            max_chars: Cap on the returned string (``<= 0`` unlimited).
            strip_scripts: html mode only: drop ``<script>`` elements. Done on a
                clone, so the live page is never mutated.
            mode: "html" for the scope's outerHTML, "text" for its innerText.
        """
        validate_choice("mode", mode, _VALID_MODES)
        session = await get_session(deps, profile)
        page = get_page(session)
        result = await page.evaluate(_build_extract_js(selector, mode, strip_scripts))
        if not result.get("matched"):
            raise ValueError(f"no element matches selector '{selector}'")
        return truncate_chars(str(result.get("value", "")), max_chars)
