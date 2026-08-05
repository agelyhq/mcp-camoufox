from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom import (
    NAMED_PROPS,
    READABLE_PROPS,
    locate_many,
    locate_visible,
    read_property,
)
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._errors import validate_choice
from camoufox_mcp.tools._target import require_one_target
from camoufox_mcp.tools._text import truncate_chars

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.dom import RegistryPage
    from camoufox_mcp.tools._base import ToolDeps

# Every prop the tool answers: the page reads, plus the one it answers without one.
_PROPS = (*READABLE_PROPS, "count")
# Counting answers about the page as it is now, so it never waits: 0 matches is a
# real answer, and burning the action budget to confirm it would make the cheapest
# question the slowest one.
_NO_WAIT = 0.0
_EMPTY = "(empty)"
_UNSET = "(not set)"

_NOT_APPLICABLE = {
    "text": "element <{tag}> has no text; use prop='value' to read what it contains",
    "value": (
        "element <{tag}> has no value; prop='value' needs an input, textarea, "
        "select or contenteditable element"
    ),
    "style": "no computed style named '{name}' on <{tag}>",
}


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def get_element(
        profile: str,
        prop: str = "text",
        uid: str | None = None,
        selector: str | None = None,
        limit: int = 1,
        max_chars: int = 4000,
        name: str | None = None,
    ) -> str:
        """Read 1 property of an element, instead of scripting it with ``evaluate``.

        Give exactly 1 of ``uid`` or ``selector``; ``prop="count"`` takes a selector
        only.

        Args:
            prop: text (rendered text), value (what a field holds), attribute (needs
                name), state (visible, enabled, checked, editable), box (viewport
                pixels, feeds click_at), style (computed, needs name), count (matches
                right now, never waits).
            limit: Matches to read; above 1 each gets a numbered line.
            max_chars: Cap per value, with a truncation note.
            name: Attribute name for ``attribute``, CSS property for ``style``.
        """
        _validate(prop, uid, selector, name)
        session = await get_session(deps, profile)
        page = get_page(session)

        if prop == "count":
            return str(await _count(page, str(selector)))

        if uid is not None:
            uids, total = [uid], 1
        else:
            uids, total = await locate_many(page, str(selector), limit=max(1, limit))

        records = await read_property(page, prop, uids, name)
        single = len(records) == 1
        return _assemble(
            [_render(prop, name, record, max_chars, single=single) for record in records], total
        )


def _validate(prop: str, uid: str | None, selector: str | None, name: str | None) -> None:
    validate_choice("prop", prop, _PROPS)
    if prop in NAMED_PROPS and not name:
        example = "name='href'" if prop == "attribute" else "name='color'"
        raise ValueError(f"prop='{prop}' needs a name, e.g. {example}")
    if prop == "count":
        if selector is None:
            raise ValueError("prop='count' needs a selector")
        if uid is not None:
            raise ValueError("prop='count' counts selector matches; drop uid")
        return
    require_one_target(uid, selector)


async def _count(page: RegistryPage, selector: str) -> int:
    """Visible matches of ``selector`` in the page as it is now."""
    found = await locate_visible(page, selector, deadline=_NO_WAIT, mint=False)
    return 0 if found is None else int(found.get("total", 0))


def _render(prop: str, name: str | None, record: Any, max_chars: int, *, single: bool) -> str:
    """One match rendered, or the reason that one match has no answer to give.

    A property that does not apply is fatal only when it is the whole answer. Among
    several matches it is one line of the report: raising there would throw away
    every match that did answer because of the one that could not.
    """
    if not isinstance(record, dict):
        raise ValueError(f"the page returned no readable record for prop '{prop}'")
    tag = str(record.get("tag", "?"))
    if not record.get("ok"):
        template = _NOT_APPLICABLE.get(prop, "prop='{prop}' does not apply to <{tag}>")
        note = template.format(prop=prop, tag=tag, name=name)
        if single:
            raise ValueError(note)
        return note
    if prop == "state":
        return (
            f"visible={_flag(record.get('visible'))} enabled={_flag(record.get('enabled'))} "
            f"checked={_flag(record.get('checked'))} editable={_flag(record.get('editable'))}"
        )
    if prop == "box":
        return _render_box(record)
    if prop == "attribute" and record.get("missing"):
        return _UNSET
    value = str(record.get("value", ""))
    if prop == "text":
        value = value.strip()
    return truncate_chars(value, max_chars) if value else _EMPTY


def _render_box(record: dict[str, Any]) -> str:
    left, top = float(record.get("x", 0)), float(record.get("y", 0))
    width, height = float(record.get("w", 0)), float(record.get("h", 0))
    return (
        f"x={round(left)} y={round(top)} w={round(width)} h={round(height)} "
        f"center=({round(left + width / 2)}, {round(top + height / 2)})"
    )


def _flag(value: Any) -> str:
    if value is None:
        return "n/a"
    return "true" if value else "false"


def _assemble(values: list[str], total: int) -> str:
    """One value on its own, or one numbered line per match, plus the match count."""
    if len(values) == 1:
        return values[0] if total <= 1 else f"{values[0]}  (1 of {total} matches)"
    lines = [f"{rank}. " + " ".join(value.splitlines()) for rank, value in enumerate(values, 1)]
    lines.append(f"({len(values)} of {total} matches)")
    return "\n".join(lines)
