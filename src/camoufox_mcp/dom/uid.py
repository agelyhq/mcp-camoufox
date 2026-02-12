from __future__ import annotations

import re
from typing import TYPE_CHECKING

from camoufox_mcp.dom.snapshot import get_resolve_uid_js

if TYPE_CHECKING:
    from collections.abc import Callable

    from camoufox_mcp.browser.page_handle import PageHandle

_UID_PATTERN = re.compile(r"^e\d+$")


def valid_uid(uid: str) -> bool:
    return bool(_UID_PATTERN.match(uid))


async def run_js_action(
    page: PageHandle, uid: str, js_loader: Callable[[], str]
) -> dict[str, object]:
    if not valid_uid(uid):
        return {"error": "Invalid UID format. Expected e0, e1, etc."}
    result = await page.evaluate(f"({js_loader()})('{uid}')")
    if not isinstance(result, dict):
        return {"error": f"Unexpected result: {result}"}
    return result


def uid_selector(uid: str) -> str:
    return f'[data-mcp-uid="{uid}"]'


async def resolve_uid(page: PageHandle, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_resolve_uid_js)
