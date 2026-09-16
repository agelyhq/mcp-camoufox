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

    The first block is geometry and dispatch. The second is identity: what the element
    is, what it is called and what it says, which is what lets the caller record an
    element a uid will not name in any later document. It is the cheap half of an
    accessible name by design — see ``identityOf`` in ``25_identity.js`` for what is
    deliberately not computed here and why — and it is computed only for a caller that
    passed ``ident=True``, which is the 3 tools whose record names what they acted on
    (``click``, ``fill``, ``fill_form``). Those 5 fields are empty strings for every
    other caller.

    ``label`` is the one name a reader wants; ``name_sources`` is every name the element
    answers to, joined. They are separate because a field labelled "Security code" and
    named ``cvc`` must stay readable as the first while still being caught by the second.
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
    role: str
    input_type: str
    label: str
    name_sources: str
    text: str


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
    ident: bool = False,
    deadline: float = ACTION_DEADLINE,
) -> Hit:
    """Scroll to, measure and classify a uid, waiting for it to settle.

    This is what replaces the driver's own actionability retry. A missing element
    fails immediately; a mis-sized, off-screen or covered one is re-probed until the
    budget runs out, then reported with the specific reason.

    ``hit`` and ``ident`` are the two halves nobody pays for by default: the hit test
    that names what covers the element, and the identity that lets a record say what was
    acted on. Both are re-run on every poll iteration, so a caller that reads neither —
    an element screenshot, the second resolve a toggle makes to aim its click — asks for
    neither. The identity fields of the resulting :class:`Hit` are then empty strings.
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
        return await element_call(
            page, "resolve", uid, {"scroll": scroll, "hit": hit, "ident": ident}
        )

    try:
        info = await poll_until(probe, accept, deadline=deadline)
    except PollExpiredError as expired:
        info = expired.last
    raise_for(info, uid, op="resolve")
    return _hit_from(info)


async def bind_selector(
    page: RegistryPage,
    selector: str,
    *,
    visible: bool = True,
    deadline: float = ACTION_DEADLINE,
) -> str:
    """Wait for the first match of ``selector`` and give it a uid.

    Supported syntax is plain CSS plus ``:has-text("...")`` and ``text=...``.
    Anything else is refused by name rather than matching nothing.

    ``visible`` is the gate every other uid mint applies. A pointer or keyboard action
    needs it, because it acts where the element is drawn; ``upload_file`` does not,
    because it hands the page a ``File`` and a site's ``<input type=file>`` is hidden
    behind its own "Add media" button as a rule, not as an exception. With
    ``visible=False`` the first probe binds whatever the CSS engine matches.

    An expiry is reported as an expiry: the message names the budget it spent and
    says whether the selector matched nothing at all or matched something that stayed
    invisible.
    """
    result = await _locate(page, selector, deadline=deadline, mint=True, limit=1, visible=visible)
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
    page: RegistryPage,
    selector: str,
    *,
    deadline: float,
    mint: bool,
    limit: int,
    visible: bool = True,
) -> dict[str, Any] | None:
    """Poll until ``selector`` matches something (visible unless told otherwise)."""

    def accept(info: Any) -> bool:
        return isinstance(info, dict) and (bool(info.get("err")) or bool(info.get("ids")))

    async def probe() -> Any:
        try:
            return await page.elements.call(
                "locate",
                {"selector": selector, "visible": visible, "limit": limit, "mint": mint},
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
