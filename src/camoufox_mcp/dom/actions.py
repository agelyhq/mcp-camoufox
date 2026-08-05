from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from camoufox_mcp.dom.errors import raise_for
from camoufox_mcp.dom.identity import element_call, resolve
from camoufox_mcp.dom.waiting import UPLOAD_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from camoufox_mcp.dom.identity import Hit
    from camoufox_mcp.dom.page_protocol import ActionablePage

# The bytes cross the protocol base64-encoded, so a ceiling is needed where the
# local-path route had none.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_TRUE_VALUES = frozenset({"true", "1", "yes", "on", "check", "checked"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", "uncheck", "unchecked", ""})


@dataclass(frozen=True)
class _Fill:
    """One fill request, already resolved. Every handler below reads the same record."""

    page: ActionablePage
    uid: str
    hit: Hit
    value: str
    clear_first: bool


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


async def fill_field(page: ActionablePage, uid: str, value: str, clear_first: bool = True) -> str:
    """Set the value of an editable element by uid, dispatching on what it is.

    A ``<select>`` picks an option, a checkbox or radio is clicked at its hit-tested
    centre, a colour or range slider takes its value directly, and everything
    editable is focused and typed into with real key events.
    """
    hit = await resolve(page, uid)
    handler = _HANDLERS.get(hit.kind)
    if handler is None:
        # Not a catch-all typed into by default: ``kindOf`` in ``10_visibility.js``
        # names a closed set, and a kind renamed there must fail here rather than be
        # silently treated as a text field.
        raise ValueError(
            f"element <{hit.tag}> for uid '{uid}' has unknown kind '{hit.kind}'; "
            f"fill knows {', '.join(sorted(_HANDLERS))}"
        )
    return await handler(_Fill(page=page, uid=uid, hit=hit, value=value, clear_first=clear_first))


def _filled(tag: str, value: str) -> str:
    """The one confirmation every value-setting path returns."""
    return f"Filled <{tag}> with {len(value)} chars"


async def set_files(page: ActionablePage, uid: str, file_path: str) -> str:
    """Attach a local file to the file input a uid points at (or controls)."""
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"'{file_path}' is not a readable file")
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"'{file_path}' is {size} bytes; upload_file accepts at most {MAX_UPLOAD_BYTES} bytes"
        )
    payload = {
        "name": path.name,
        "type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
    info = await element_call(page, "setFiles", uid, payload, timeout=UPLOAD_TIMEOUT)
    raise_for(info, uid, op="setFiles")
    return f"Uploaded {file_path} to {uid}"


async def _type_into(request: _Fill) -> str:
    page, uid, value = request.page, request.uid, request.value
    info = await element_call(page, "prepareFill", uid, {"clear": request.clear_first})
    raise_for(info, uid, op="prepareFill")
    if request.clear_first and info.get("had"):
        # A real selection plus a real Delete: trusted beforeinput/input, where
        # assigning an empty value would fake both.
        await page.raw.keyboard.press("Delete")
    elif info.get("needsEnd"):
        await page.raw.keyboard.press("End")
    await page.raw.keyboard.type(value)
    return _filled(str(info.get("tag", "?")), value)


async def _assign_value(request: _Fill) -> str:
    """A colour or range control takes its value directly; there is nothing to type."""
    info = await element_call(
        request.page, "prepareFill", request.uid, {"mode": "set", "value": request.value}
    )
    raise_for(info, request.uid, op="prepareFill")
    return _filled(request.hit.tag, request.value)


async def _select_option(request: _Fill) -> str:
    page, uid, value = request.page, request.uid, request.value
    info = await element_call(page, "selectOptions", uid, {})
    raise_for(info, uid, op="selectOptions")
    options = info.get("options")
    if not isinstance(options, list):
        raise ValueError(f"could not read the options of uid '{uid}'")
    matched = _match_option(options, value)
    if matched is None:
        available = ", ".join(repr(str(o.get("label") or o.get("value"))) for o in options)
        raise ValueError(f"no option matching '{value}'; available options are {available}")
    applied = await element_call(page, "selectOption", uid, {"value": matched})
    raise_for(applied, uid, op="selectOption")
    return f"Selected '{value}' in <select>"


async def _set_toggle(request: _Fill) -> str:
    hit, uid = request.hit, request.uid
    wanted = _parse_toggle(request.value)
    if hit.disabled:
        raise ValueError(f"element <{hit.tag}> for uid '{uid}' is disabled")
    if hit.checked is wanted:
        return f"<{hit.tag}> is already {'checked' if wanted else 'unchecked'}"
    target = await resolve(request.page, uid, hit=True)
    await request.page.raw.mouse.click(target.x, target.y)
    return f"{'Checked' if wanted else 'Unchecked'} <{hit.tag}>"


async def _refuse_file(request: _Fill) -> str:
    raise ValueError(f"uid '{request.uid}' is a file input; use upload_file")


async def _refuse_other(request: _Fill) -> str:
    raise ValueError(
        f"element <{request.hit.tag}> is not editable; "
        f"fill only accepts input, textarea, select or contenteditable elements"
    )


# Every kind ``kindOf`` (10_visibility.js) can report, mapped to the one path that
# handles it. Exhaustive by construction: a kind absent from here is an error, not a
# default.
_HANDLERS: dict[str, Callable[[_Fill], Awaitable[str]]] = {
    "select": _select_option,
    "toggle": _set_toggle,
    "set": _assign_value,
    "file": _refuse_file,
    "other": _refuse_other,
    "text": _type_into,
    "rich": _type_into,
}


def _parse_toggle(value: str) -> bool:
    folded = value.strip().casefold()
    if folded in _TRUE_VALUES:
        return True
    if folded in _FALSE_VALUES:
        return False
    raise ValueError(
        f"'{value}' is not a checkbox state; use one of 'true', 'false', 'checked', 'unchecked'"
    )
