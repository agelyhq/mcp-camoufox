from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom.snapshot import (
    get_clear_field_js,
    get_file_input_selector_js,
    get_scroll_into_view_js,
)
from camoufox_mcp.dom.uid import run_js_action

if TYPE_CHECKING:
    from camoufox_mcp.browser.page_handle import PageHandle


async def clear_field(page: PageHandle, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_clear_field_js)


async def scroll_into_view(page: PageHandle, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_scroll_into_view_js)


async def file_input_selector(page: PageHandle, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_file_input_selector_js)
