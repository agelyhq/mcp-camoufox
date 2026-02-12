from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context  # noqa: TC002

if TYPE_CHECKING:
    from camoufox_mcp.browser.manager import BrowserManager
    from camoufox_mcp.browser.page_handle import PageHandle


def get_manager(ctx: Context) -> BrowserManager:
    return ctx.request_context.lifespan_context


def get_page(ctx: Context) -> PageHandle:
    return get_manager(ctx).active_page
