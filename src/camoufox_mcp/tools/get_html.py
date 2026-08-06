from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import MARKUP_MODES, read_markup
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._errors import validate_choice
from camoufox_mcp.tools._text import truncate_chars

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


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
        validate_choice("mode", mode, MARKUP_MODES)
        session = await get_session(deps, profile)
        page = get_page(session)
        markup = await read_markup(page, selector=selector, mode=mode, strip_scripts=strip_scripts)
        return truncate_chars(markup, max_chars)
