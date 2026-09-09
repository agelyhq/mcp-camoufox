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

# How much of one piece of page-written text a message here may echo. Long enough to
# identify an <option> a human would recognise, short enough that a page cannot size a
# line the record keeps unredacted.
MAX_ECHOED_CHARS = 80

# How many of them one message may list. Capping each <option> bounds a label and not the
# LIST, and a <select> holding thousands of them is a page sizing the line after all: a
# megabyte message handed to the model and written to the record's ``error``, which
# nothing truncates. 20 is chosen against the caller this message exists for, someone who
# mistyped one option and needs to see enough real ones to correct themselves; past that
# the fix is to read the <select>, not the error.
MAX_ECHOED_OPTIONS = 20

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


def _elided(value: str) -> str:
    """A caller-supplied value's shape, for a message that outlives the call.

    Every message built here is returned to the agent AND written to the telemetry
    record as its ``error`` and its ``result``, neither of which is redacted: only
    ``args`` is. This layer cannot tell a search term from a credential — that reads the
    4 names a field carries and lives in ``tools/_secrets.py``, an outer layer this one
    may not import — so it never writes a typed value into a message at all. Nothing is
    lost: the value is already in ``args``, redacted there exactly when it must be, and
    what makes each failure diagnosable is the rest of the sentence. Same
    length-preserving shape as the ``<N bytes>`` an elided payload gets.
    """
    return f"<{len(value)} chars>"


def _match_option(options: list[dict[str, str]], value: str) -> dict[str, str] | None:
    """The option matching ``value`` exactly by value, then exactly by label, then by
    label again with case folded.

    The third pass folds the LABEL only: an option's value is an identifier the form
    submits, and accepting ``READ`` for ``read`` would silently submit something the
    caller did not name.

    The OPTION rather than its value, because the caller of this needs both halves: the
    value to apply, and the way the page spells the option, which is the only spelling
    that may be echoed back (see :func:`_option_name`).
    """
    for key in ("value", "label"):
        for option in options:
            if option.get(key) == value:
                return option
    folded = value.casefold()
    for option in options:
        if option.get("label", "").casefold() == folded:
            return option
    return None


def _option_name(option: dict[str, str]) -> str:
    """How the PAGE spells the option that won: its label, or its value when it has none.

    Capped, because it is page content on its way into a message that is both the tool
    result and the record's unredacted ``result``: an <option> label has no length limit
    of its own, and the page cannot be allowed to size a line by writing one. It is not
    capped in the page instead, where a truncated label would stop matching a caller who
    named it in full.
    """
    return _capped(option.get("label") or option.get("value", ""))


def _capped(text: str) -> str:
    return text if len(text) <= MAX_ECHOED_CHARS else f"{text[:MAX_ECHOED_CHARS]}..."


def _available(options: list[dict[str, str]]) -> str:
    """The options an error is allowed to list, and a count of the ones it did not.

    Same ``... (N more)`` shape the captured-request renderer uses for headers, so a
    reader meets one elision convention rather than two.
    """
    shown = ", ".join(repr(_option_name(o)) for o in options[:MAX_ECHOED_OPTIONS])
    hidden = len(options) - MAX_ECHOED_OPTIONS
    return f"{shown} ... ({hidden} more)" if hidden > 0 else shown


async def fill_field(
    page: ActionablePage,
    uid: str,
    value: str,
    clear_first: bool = True,
    *,
    on_resolved: Callable[[Hit], None] | None = None,
) -> str:
    """Set the value of an editable element by uid, dispatching on what it is.

    A ``<select>`` picks an option, a checkbox or radio is clicked at its hit-tested
    centre, a colour or range slider takes its value directly, and everything
    editable is focused and typed into with real key events.

    ``on_resolved`` is handed the element the moment it is measured, out of the one
    ``resolve`` this already makes: a caller that records what it filled neither pays a
    second page turn for the answer nor waits for success to learn it. Waiting would
    lose exactly the case that matters, a value typed into a field the fill could not
    finish, which is the one that must not reach the log in clear.
    """
    # The identity is measured only when someone is waiting for it: it is re-read on
    # every poll iteration, and a fill nobody records has no use for it.
    hit = await resolve(page, uid, ident=on_resolved is not None)
    if on_resolved is not None:
        on_resolved(hit)
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
        raise ValueError(
            f"no option matches the value given ({_elided(value)}); "
            f"available options are {_available(options)}"
        )
    applied = await element_call(page, "selectOption", uid, {"value": matched["value"]})
    raise_for(applied, uid, op="selectOption")
    # The page's spelling of the option that won, never the argument that asked for it:
    # the case-insensitive branch of _match_option accepts "banana" for "Banana", so
    # echoing the caller back would put a caller-supplied string into a message that is
    # also the telemetry ``result``, which redaction never rewrites (see _elided). The
    # matched label is page content, and it is the more useful of the two anyway.
    return f"Selected '{_option_name(matched)}' in <select>"


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
        f"the value given ({_elided(value)}) is not a checkbox state; "
        f"use one of 'true', 'false', 'checked', 'unchecked'"
    )
