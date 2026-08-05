"""One rendering of one open tab, shared by the 2 tools that list tabs.

``list_pages`` and ``list_sessions`` show the same thing at different scopes, so they
show it the same way: an agent should not have to re-read a line because a different
tool printed it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox_mcp.sessions.page_book import PageInfo


async def format_tab_line(info: PageInfo) -> str:
    """``[index]* title  url``, the active tab carrying the star."""
    marker = "*" if info.is_active else " "
    return f"[{info.index}]{marker} {await info.page.title()}  {info.page.url}"
