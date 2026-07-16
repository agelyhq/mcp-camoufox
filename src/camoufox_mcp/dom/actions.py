from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom.snapshot import (
    get_clear_field_js,
    get_file_input_selector_js,
    get_scroll_into_view_js,
)
from camoufox_mcp.dom.uid import resolve_uid_or_raise, run_js_action, uid_selector

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import ActionablePage, EvaluatablePage


async def clear_field(page: EvaluatablePage, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_clear_field_js)


async def scroll_into_view(page: EvaluatablePage, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_scroll_into_view_js)


async def resolve_center(page: EvaluatablePage, uid: str) -> tuple[float, float, str]:
    """Resolve a uid, scroll it into view, re-resolve, and return its ``(x, y, tag)`` center."""
    await resolve_uid_or_raise(page, uid)
    await scroll_into_view(page, uid)
    info = await resolve_uid_or_raise(page, uid)
    return info["x"], info["y"], str(info.get("tag", "?"))


async def file_input_selector(page: EvaluatablePage, uid: str) -> dict[str, object]:
    return await run_js_action(page, uid, get_file_input_selector_js)


async def fill_field(page: ActionablePage, uid: str, value: str, clear_first: bool = True) -> str:
    """Focus an editable element by uid and type ``value`` into it.

    Resolves the uid, verifies it is editable, scrolls it into view, focuses it,
    optionally clears it, then types. Raises ``ValueError`` for unknown/stale uids
    or non-editable elements. Returns ``Filled <tag> with N chars``.
    """
    info = await resolve_uid_or_raise(page, uid)
    tag = info.get("tag", "?")
    if not info.get("editable", False):
        raise ValueError(
            f"element <{tag}> is not editable; "
            f"fill only accepts input, textarea, select or contenteditable elements"
        )
    await scroll_into_view(page, uid)
    selector = uid_selector(uid)
    await page.raw.focus(selector)
    if clear_first:
        await clear_field(page, uid)
    await page.raw.type(selector, value)
    return f"Filled <{tag}> with {len(value)} chars"
