from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom.errors import DeadContextError, raise_for, stale_uid
from camoufox_mcp.dom.waiting import (
    ACTION_DEADLINE,
    OP_TIMEOUT,
    PollExpiredError,
    poll_until,
    render_deadline,
)

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import RegistryPage

# Sub-pixel jitter must not defeat the stability gate.
_RECT_EPSILON = 0.5
_RECT_FIELDS = ("left", "top", "width", "height")

# The 2 ways a bounded selector wait ends with nothing to act on. Telling them apart
# is the difference between "your selector is wrong" and "the page was not ready", and
# the old single string asserted the first while meaning either. Both name the budget
# that was spent and the tool whose timeout is per call, so an agent can act on the
# message instead of re-editing a selector that was already correct.
_MISS_NEVER = (
    "no element matches selector '{selector}'; nothing matched at any point during the "
    "{waited} wait, so check the selector, or wait for it first with "
    "wait_for(condition='selector', timeout=<ms>)"
)
_MISS_HIDDEN = (
    "selector '{selector}' matched {count} but none became visible during the {waited} "
    "wait; wait for it first with wait_for(condition='selector', timeout=<ms>), or "
    "target an element that is displayed"
)


@dataclass(frozen=True)
class Hit:
    """One element measured and classified in a single page turn.

    Every field here is read by a caller, and the ``resolve`` payload carries exactly
    these keys and no others. The list is not repeated anywhere: :func:`_hit_from`
    derives it from this declaration, so adding a field here without adding it to
    ``50_geometry.js`` fails loudly on the next resolve instead of quietly arriving as
    ``None``.
    """

    x: float
    y: float
    left: float
    top: float
    width: float
    height: float
    tag: str
    kind: str
    disabled: bool
    checked: bool | None


def _hit_from(info: dict[str, Any]) -> Hit:
    """Build a :class:`Hit` from a ``resolve`` payload, or say which key is missing.

    A silent ``None`` here is not a cosmetic loss. ``checked`` defaulted to ``None``
    makes the already-set test in ``actions.py`` never hold, so a checkbox that is
    already in the wanted state gets clicked blind and toggled the wrong way.
    """
    values: dict[str, Any] = {}
    for field in fields(Hit):
        if field.name not in info:
            raise ValueError(f"the page's resolve payload has no '{field.name}' field")
        values[field.name] = info[field.name]
    return Hit(**values)


async def element_call(
    page: RegistryPage, op: str, uid: str, arg: dict[str, Any], *, timeout: float = OP_TIMEOUT
) -> Any:
    """Run a uid-addressed operation, converting a dead context to the stale error.

    A navigation between the snapshot and the action is the single most common
    agent mistake, and the mandated string is the only answer that tells it what to
    do next. Nothing is re-executed.
    """
    try:
        return await page.elements.call(op, {**arg, "id": uid}, timeout=timeout)
    except DeadContextError as exc:
        raise ValueError(stale_uid(uid)) from exc


async def resolve(
    page: RegistryPage,
    uid: str,
    *,
    scroll: bool = True,
    hit: bool = False,
    deadline: float = ACTION_DEADLINE,
) -> Hit:
    """Scroll to, measure and classify a uid, waiting for it to settle.

    This is what replaces the driver's own actionability retry. A missing element
    fails immediately; a mis-sized, off-screen or covered one is re-probed until the
    budget runs out, then reported with the specific reason.
    """
    previous: dict[str, Any] | None = None

    def accept(info: Any) -> bool:
        nonlocal previous
        if not isinstance(info, dict):
            return True
        if info.get("err") == "unknown":
            return True
        prev, previous = previous, info
        if "err" in info or info.get("intercept"):
            return False
        return prev is not None and _same_rect(prev, info)

    async def probe() -> Any:
        return await element_call(page, "resolve", uid, {"scroll": scroll, "hit": hit})

    try:
        info = await poll_until(probe, accept, deadline=deadline)
    except PollExpiredError as expired:
        info = expired.last
    raise_for(info, uid, op="resolve")
    return _hit_from(info)


async def bind_selector(
    page: RegistryPage, selector: str, *, deadline: float = ACTION_DEADLINE
) -> str:
    """Wait for the first visible match of ``selector`` and give it a uid.

    Supported syntax is plain CSS plus ``:has-text("...")`` and ``text=...``.
    Anything else is refused by name rather than matching nothing.

    An expiry is reported as an expiry: the message names the budget it spent and
    says whether the selector matched nothing at all or matched something that stayed
    invisible.
    """
    result = await locate_visible(page, selector, deadline=deadline, mint=True)
    if result is None:
        raise ValueError(await _miss_message(page, selector, deadline))
    return str(result["ids"][0])


async def _miss_message(page: RegistryPage, selector: str, deadline: float) -> str:
    """Name what the expired wait actually saw, in one line.

    The extra probe drops the visibility filter, which is the only question the poll
    itself never answers: it looked for a visible match and found none, and an element
    present but hidden is a different problem with a different fix.
    """
    waited = render_deadline(deadline)
    present = await _count_any(page, selector)
    if present <= 0:
        return _MISS_NEVER.format(selector=selector, waited=waited)
    count = "1 element" if present == 1 else f"{present} elements"
    return _MISS_HIDDEN.format(selector=selector, count=count, waited=waited)


async def _count_any(page: RegistryPage, selector: str) -> int:
    """Matches of ``selector`` right now, visible or not; 0 when the page cannot say.

    This runs after a failure and must never replace it: a dead context or a payload
    we cannot read means the caller keeps the plain "nothing matched" reading.
    """
    try:
        found = await page.elements.call(
            "locate", {"selector": selector, "visible": False, "limit": 1, "mint": False}
        )
    except DeadContextError:
        return 0
    if not isinstance(found, dict) or found.get("err"):
        return 0
    return int(found.get("total", 0))


async def locate_visible(
    page: RegistryPage, selector: str, *, deadline: float, mint: bool
) -> dict[str, Any] | None:
    """Poll until ``selector`` has a visible match; return the payload or None."""
    return await _locate(page, selector, deadline=deadline, mint=mint, limit=1)


async def locate_many(
    page: RegistryPage, selector: str, *, limit: int, deadline: float = ACTION_DEADLINE
) -> tuple[list[str], int]:
    """Wait for ``selector``, mint a uid for up to ``limit`` matches, report the total.

    This is the whole multi-match surface a caller needs, so no tool has to address
    the element store itself to read past the first match. The total counts what
    matched before ``limit`` was applied, which is what lets a caller say it is
    looking at 2 of 7.
    """
    found = await _locate(page, selector, deadline=deadline, mint=True, limit=max(1, limit))
    if found is None:
        raise ValueError(f"no element matches '{selector}'")
    uids = [str(found_id) for found_id in found.get("ids", [])]
    if not uids:
        raise ValueError(f"no element matches '{selector}'")
    return uids, int(found.get("total", len(uids)))


async def _locate(
    page: RegistryPage, selector: str, *, deadline: float, mint: bool, limit: int
) -> dict[str, Any] | None:
    """Poll until ``selector`` matches something visible; return the payload or None."""

    def accept(info: Any) -> bool:
        return isinstance(info, dict) and (bool(info.get("err")) or bool(info.get("ids")))

    async def probe() -> Any:
        try:
            return await page.elements.call(
                "locate", {"selector": selector, "visible": True, "limit": limit, "mint": mint}
            )
        except DeadContextError:
            # The document went away mid-poll: the next probe rebuilds the store.
            return {"ids": []}

    try:
        found = await poll_until(probe, accept, deadline=deadline)
    except PollExpiredError:
        return None
    raise_for(found, selector, op="locate")
    return found


async def scroll_uid(page: RegistryPage, uid: str) -> str:
    """Bring an element into view and return its tag name."""
    info = await element_call(page, "scrollTo", uid, {})
    raise_for(info, uid, op="scrollTo")
    return str(info.get("tag", "?"))


def _same_rect(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    for field in _RECT_FIELDS:
        before = previous.get(field)
        after = current.get(field)
        if before is None or after is None:
            return False
        if abs(float(before) - float(after)) > _RECT_EPSILON:
            return False
    return True
