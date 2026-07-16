from __future__ import annotations

import json
from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool
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

        Reflects the live, post-JavaScript DOM (not the original network response).
        Prefer ``mode="text"`` with a ``selector`` as the cheap way to read page
        content: it returns just the rendered text of one region instead of a whole
        document of markup.

        Params:
            profile: The browser profile whose active tab is read.
            selector: CSS selector scoping the output to the FIRST matching element.
                When ``None`` (default) the whole document is used. A selector that
                matches nothing raises a ValueError.
            max_chars: Cap on the returned string length (default 20000). When the
                content is longer, it is cut to ``max_chars`` and a
                ``"\\n[truncated N chars]"`` note (N = characters removed) is
                appended. ``max_chars <= 0`` means unlimited.
            strip_scripts: html mode only. When true (default), ``<script>`` elements
                are removed before serializing. The removal happens on a clone, so the
                live page is never mutated.
            mode: ``"html"`` (default) returns the scope's ``outerHTML``; ``"text"``
                returns the scope's ``innerText`` (rendered visible text).

        Returns:
            The requested HTML or text, capped per ``max_chars``.

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: ValueError: no element matches selector '<sel>'" if a selector
              matched nothing.
            - "Error: ValueError: invalid mode '<mode>'; ..." for an unknown mode.
            - "Error: ProfileInUseError: ..." if the profile lock is held.
        """
        if mode not in _VALID_MODES:
            raise ValueError(
                f"invalid mode '{mode}'; valid values: {', '.join(map(repr, _VALID_MODES))}"
            )
        session = await get_session(deps, profile)
        page = get_page(session)
        result = await page.evaluate(_build_extract_js(selector, mode, strip_scripts))
        if not result.get("matched"):
            raise ValueError(f"no element matches selector '{selector}'")
        return truncate_chars(str(result.get("value", "")), max_chars)
