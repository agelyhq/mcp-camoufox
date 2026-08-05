from __future__ import annotations

import json
from typing import Any

# The driver's own serializer replaces these 3 object types with a marker string
# before the value ever leaves the page (``serialize`` in coreBundle.js). Firefox
# does not raise on them and neither does the driver, so without this table a
# script returning ``document.body`` yields the literal text "ref: <Node>" and the
# caller is told nothing at all.
_HANDLE_MARKERS = {
    "ref: <Node>": "a DOM node",
    "ref: <Document>": "the document",
    "ref: <Window>": "the window",
}

_HANDLE_HINT = (
    "which cannot be serialized out of the page; return a property instead, "
    "for example el.textContent, el.id or el.getBoundingClientRect()"
)

_CIRCULAR_MESSAGE = (
    "script returned a circular structure, which cannot be serialized; "
    "return a plain copy of the fields you need instead"
)

_ROOT = "result"

# The next action, which is the only part of the note that differs between callers.
# A caller with an adjustable cap names its own parameter; a caller with a fixed one
# says so where it is declared, because sending a caller after a knob it cannot reach
# is worse than telling it the cap is fixed.
RAISE_MAX_CHARS = "Raise max_chars to see more"
_JSON_FRAGMENT = "Cut mid-value, so this is a fragment and not valid JSON. " + RAISE_MAX_CHARS


def truncation_note(shown: int, total: int, unit: str, advice: str) -> str:
    """Build the product's one truncation note.

    Every note has the same 3 parts: what came back, what exists in full, and what to
    do next. Stating the total and the next action is what turns a truncation into a
    follow-up call instead of a dead end, so no caller gets to emit a shorter form.
    """
    return f"[truncated: showing {shown} of {total} {unit}. {advice}]"


def truncate_chars(text: str, max_chars: int, advice: str = RAISE_MAX_CHARS) -> str:
    """Cap ``text`` at ``max_chars`` and append the truncation note.

    ``advice`` is the caller's own next action, defaulting to the common case of a
    ``max_chars`` parameter the caller exposes under that name.
    ``max_chars <= 0`` returns ``text`` unchanged (unlimited).
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n" + truncation_note(max_chars, len(text), "chars", advice)


def render_capped(value: Any, max_chars: int, max_items: int) -> str:
    """JSON-serialize ``value`` under both caps, keeping a list result valid JSON.

    A list is cut at an element boundary, by ``max_items`` first and by ``max_chars``
    second, so what comes back still parses. Anything else is cut at ``max_chars``,
    which is a character boundary and cannot leave a parseable document, so that note
    says outright that the result is a fragment rather than letting the caller find
    out in a parser.

    A value the page could not hand over (a DOM node, the document, the window, or a
    circular structure) raises instead of being rendered as a marker string or as a
    Python repr.

    Both caps take ``<= 0`` to mean unlimited.
    """
    _reject_handles(value)
    if isinstance(value, list):
        return _render_list(value, max_chars, max_items)
    return truncate_chars(_dumps(value), max_chars, _JSON_FRAGMENT)


def _dumps(value: Any) -> str:
    """Serialize one value, naming the 1 failure the page can actually produce.

    ``default=str`` keeps a stray non-JSON scalar (a date the driver parsed into a
    Python object) inside an otherwise valid document instead of collapsing the
    whole result into a repr.
    """
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except ValueError as exc:
        raise ValueError(_CIRCULAR_MESSAGE) from exc


def _render_list(value: list[Any], max_chars: int, max_items: int) -> str:
    total = len(value)
    allowed = total if max_items <= 0 else min(max_items, total)
    # Only the elements that can still be emitted are serialized: on the call this
    # cap exists for, that is 200 of 5341 instead of all of them.
    parts = [_dumps(item) for item in value[:allowed]]
    kept = _fit(parts, allowed, max_chars)
    body = "[" + ", ".join(parts[:kept]) + "]"
    if kept == total:
        return body
    limiter = "max_items" if kept == allowed else "max_chars"
    advice = f"Raise {limiter} to see more"
    return f"{body}\n" + truncation_note(kept, total, "items", advice)


def _fit(parts: list[str], allowed: int, max_chars: int) -> int:
    """How many of the first ``allowed`` elements fit in ``max_chars`` once joined."""
    if max_chars <= 0:
        return allowed
    used = len("[]")
    for index in range(allowed):
        added = len(parts[index]) + (len(", ") if index else 0)
        if used + added > max_chars:
            return index
        used += added
    return allowed


def _reject_handles(value: Any) -> None:
    """Raise when a marker string for an unserializable object sits anywhere inside.

    The walk is an explicit stack, not recursion: a page can nest deeper than the
    interpreter's limit, and a value carrying a cycle would otherwise never end.
    """
    seen: set[int] = set()
    stack: list[tuple[str, Any]] = [(_ROOT, value)]
    while stack:
        path, node = stack.pop()
        if isinstance(node, str):
            _reject_marker(path, node)
        elif isinstance(node, dict) and id(node) not in seen:
            seen.add(id(node))
            stack.extend((f"{path}.{key}", item) for key, item in node.items())
        elif isinstance(node, list) and id(node) not in seen:
            seen.add(id(node))
            stack.extend((f"{path}[{index}]", item) for index, item in enumerate(node))


def _reject_marker(path: str, node: str) -> None:
    subject = _HANDLE_MARKERS.get(node)
    if subject is None:
        return
    where = "" if path == _ROOT else f" at {path}"
    raise ValueError(f"script returned {subject}{where}, {_HANDLE_HINT}")
