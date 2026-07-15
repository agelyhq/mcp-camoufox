from __future__ import annotations

import re
from typing import TYPE_CHECKING

from camoufox_mcp.dom.snapshot import get_resolve_uid_js

if TYPE_CHECKING:
    from collections.abc import Callable

    from camoufox_mcp.dom.page_protocol import EvaluatablePage

_UID_PATTERN = re.compile(r"^e\d+$")


def valid_uid(uid: str) -> bool:
    return bool(_UID_PATTERN.match(uid))


async def run_js_action(
    page: EvaluatablePage, uid: str, js_loader: Callable[[], str]
) -> dict[str, object]:
    if not valid_uid(uid):
        return {"error": "Invalid UID format. Expected e0, e1, etc."}
    result = await page.evaluate(f"({js_loader()})('{uid}')")
    if not isinstance(result, dict):
        return {"error": f"Unexpected result: {result}"}
    return result


def uid_selector(uid: str) -> str:
    return f'[data-mcp-uid="{uid}"]'


async def resolve_uid(page: EvaluatablePage, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_resolve_uid_js)


async def resolve_uid_or_raise(page: EvaluatablePage, uid: str) -> dict[str, object]:
    """Resolve a snapshot uid or raise the canonical stale-uid error.

    Returns the element info dict; raises ``ValueError`` when the uid is invalid or
    the page changed since the snapshot.
    """
    info = await resolve_uid(page, uid)
    if "error" in info:
        raise ValueError(f"unknown or stale uid '{uid}'; take a new snapshot")
    return info


async def resolve_center(page: EvaluatablePage, uid: str) -> tuple[float, float, str]:
    """Resolve a uid, scroll it into view, re-resolve, and return its ``(x, y, tag)`` center."""
    from camoufox_mcp.dom.actions import scroll_into_view

    await resolve_uid_or_raise(page, uid)
    await scroll_into_view(page, uid)
    info = await resolve_uid_or_raise(page, uid)
    return info["x"], info["y"], str(info.get("tag", "?"))
