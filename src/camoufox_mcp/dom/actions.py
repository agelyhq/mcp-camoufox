from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom.snapshot import (
    get_clear_field_js,
    get_file_input_selector_js,
    get_scroll_into_view_js,
    get_select_options_js,
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


def _match_option(options: list[dict[str, str]], value: str) -> str | None:
    """Find the option value matching ``value`` by value, then label, then case-insensitively."""
    for key in ("value", "label"):
        for option in options:
            if option.get(key) == value:
                return option["value"]
    folded = value.casefold()
    for option in options:
        if option.get("label", "").casefold() == folded:
            return option["value"]
    return None


async def _select_option(page: ActionablePage, uid: str, selector: str, value: str) -> str:
    """Pick an option in a ``<select>``, matching on value, then label, then case-insensitively."""
    info = await run_js_action(page, uid, get_select_options_js)
    options = info.get("options")
    if not isinstance(options, list):
        raise ValueError(f"could not read the options of uid '{uid}'")
    matched = _match_option(options, value)
    if matched is None:
        available = ", ".join(repr(str(o.get("label") or o.get("value"))) for o in options)
        raise ValueError(f"no option matching '{value}'; available options are {available}")
    await page.raw.select_option(selector, value=matched)
    return f"Selected '{value}' in <select>"


async def fill_field(page: ActionablePage, uid: str, value: str, clear_first: bool = True) -> str:
    """Set the value of an editable element by uid.

    Resolves the uid, verifies it is editable, and scrolls it into view. A
    ``<select>`` picks the matching option (by value, falling back to label);
    anything else is focused, optionally cleared, then typed into. Raises
    ``ValueError`` for unknown/stale uids or non-editable elements.
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
    if tag == "select":
        return await _select_option(page, uid, selector, value)
    await page.raw.focus(selector)
    if clear_first:
        await clear_field(page, uid)
    await page.raw.type(selector, value)
    return f"Filled <{tag}> with {len(value)} chars"
