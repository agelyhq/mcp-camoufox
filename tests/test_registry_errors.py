"""Only a dead execution context may be reported as a stale uid.

The store behind a tab is the tab's whole uid namespace. Dropping it renumbers from
``e0``, so every uid the agent already holds silently starts naming a different
element on the same document. That price is worth paying exactly once, when the
execution context is genuinely gone and the uids were lost anyway. A protocol
hiccup, a driver timeout or a defect of ours must surface as what it is and leave
the store standing.

The driver has no exception class for a destroyed context, so the classification
rests on the wording it throws. These strings are measured, not assumed: on
camoufox 0.5.4 / Firefox 152.0.4-beta.28 with playwright 1.60, 12 of 12 navigation
races plus an iframe removal all produced ``Execution context was destroyed, most
likely because of a navigation`` as a base ``Error``, while a closed tab produced
``TargetClosedError`` as its own class.

The second half of the file pins the other direction: when our own page script
breaks, the message must name which of our operations broke.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from playwright.async_api import Error as DriverError
from playwright.async_api import TimeoutError as DriverTimeout

from camoufox_mcp.dom import registry as registry_module
from camoufox_mcp.dom.actions import fill_field, set_files
from camoufox_mcp.dom.capture import capture_snapshot
from camoufox_mcp.dom.errors import DeadContextError
from camoufox_mcp.dom.identity import bind_selector, element_call, resolve, scroll_uid
from camoufox_mcp.dom.registry import ElementRegistry
from camoufox_mcp.dom.scripting import evaluate_with_uids
from camoufox_mcp.sessions.errors import PLAYWRIGHT_TARGET_CLOSED_ERROR

if TYPE_CHECKING:
    from collections.abc import Callable

DEAD_CONTEXT = (
    "JSHandle.evaluate: Execution context was destroyed, most likely because of a navigation"
)
HICCUP = "Protocol error (Runtime.callFunctionOn): Cannot find object with given id"
STALE = "unknown or stale uid '{uid}'; take a new snapshot"
INTERNAL = {"err": "internal", "msg": "el.select is not a function"}


class _FakeHandle:
    """A page-side handle whose answers, and whose disposal, are scripted."""

    def __init__(self, respond: Callable[[dict[str, Any]], Any], *, hang_dispose: bool = False):
        self._respond = respond
        self._hang_dispose = hang_dispose
        self.ops: list[str] = []
        self.disposed = 0

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        payload = dict(arg or {})
        self.ops.append(str(payload.get("op")))
        outcome = self._respond(payload)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def dispose(self) -> None:
        self.disposed += 1
        if self._hang_dispose:
            await asyncio.sleep(3600)


class _FakeKeyboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def press(self, key: str) -> None:
        self.events.append(("press", key))

    async def type(self, text: str) -> None:
        self.events.append(("type", text))


class _FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[float, float]] = []

    async def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))


class _FakeRaw:
    def __init__(self) -> None:
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()


class _FakePage:
    """An evaluatable page owning a real registry, over scripted handles.

    Each ``evaluate_handle`` stands for one execution context, so ``built`` counts
    exactly how many times the tab's uid namespace was thrown away and rebuilt.
    """

    def __init__(self, *handles: _FakeHandle) -> None:
        self._handles = list(handles)
        self.built = 0
        self.raw = _FakeRaw()
        self.elements = ElementRegistry(self, target_closed=PLAYWRIGHT_TARGET_CLOSED_ERROR)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return None

    async def evaluate_handle(self, expression: str, arg: Any = None) -> _FakeHandle:
        self.built += 1
        return self._handles.pop(0)


def _sequence(*outcomes: Any) -> Callable[[dict[str, Any]], Any]:
    queue = list(outcomes)
    return lambda _: queue.pop(0) if queue else {"ok": True}


def _per_op(replies: dict[str, Any]) -> Callable[[dict[str, Any]], Any]:
    return lambda payload: replies[str(payload.get("op"))]


def _hit(kind: str) -> dict[str, Any]:
    return {
        "x": 10.0,
        "y": 20.0,
        "left": 5.0,
        "top": 15.0,
        "width": 10.0,
        "height": 10.0,
        "tag": "input",
        "type": "text",
        "kind": kind,
        "disabled": False,
        "readonly": False,
        "checked": None,
        "name": "Field",
        "intercept": None,
    }


async def test_a_transient_failure_surfaces_as_itself_and_keeps_the_store() -> None:
    """A protocol hiccup is not element staleness, and costs no uids."""
    handle = _FakeHandle(_sequence(DriverError(HICCUP), {"ok": True}))
    page = _FakePage(handle)

    with pytest.raises(DriverError) as raised:
        await page.elements.call("resolve", {"id": "e1"})
    assert HICCUP in str(raised.value)

    assert handle.disposed == 0
    assert await page.elements.call("resolve", {"id": "e1"}) == {"ok": True}
    # One context for both calls: every uid the caller holds still names its element.
    assert page.built == 1


async def test_only_a_dead_context_renders_the_mandated_stale_uid_string() -> None:
    dead = _FakePage(_FakeHandle(_sequence(DriverError(DEAD_CONTEXT))))
    with pytest.raises(ValueError) as staled:
        await element_call(dead, "resolve", "e7", {})
    assert str(staled.value) == STALE.format(uid="e7")

    hiccup = _FakePage(_FakeHandle(_sequence(DriverError(HICCUP))))
    with pytest.raises(DriverError) as raised:
        await element_call(hiccup, "resolve", "e7", {})
    assert "take a new snapshot" not in str(raised.value)


async def test_only_a_dead_context_throws_the_uid_namespace_away() -> None:
    dead_handle = _FakeHandle(_sequence(DriverError(DEAD_CONTEXT)))
    dead = _FakePage(dead_handle, _FakeHandle(_sequence({"ok": True})))
    with pytest.raises(DeadContextError):
        await dead.elements.call("resolve", {"id": "e1"})
    assert dead_handle.disposed == 1
    assert await dead.elements.call("resolve", {"id": "e1"}) == {"ok": True}
    assert dead.built == 2

    hiccup_handle = _FakeHandle(_sequence(DriverError(HICCUP), {"ok": True}))
    hiccup = _FakePage(hiccup_handle)
    with pytest.raises(DriverError):
        await hiccup.elements.call("resolve", {"id": "e1"})
    assert hiccup_handle.disposed == 0
    assert await hiccup.elements.call("resolve", {"id": "e1"}) == {"ok": True}
    assert hiccup.built == 1


async def test_a_driver_timeout_is_not_element_staleness() -> None:
    """The driver's TimeoutError is not the builtin, so it used to fall through."""
    assert not issubclass(DriverTimeout, TimeoutError)

    handle = _FakeHandle(_sequence(DriverTimeout("Timeout 30000ms exceeded.")))
    page = _FakePage(handle)

    with pytest.raises(DriverTimeout):
        await element_call(page, "resolve", "e1", {})
    assert handle.disposed == 0
    assert page.built == 1


async def test_a_closed_tab_is_re_raised_by_type() -> None:
    """Mapping a browser that is gone to "take a new snapshot" is an infinite loop."""
    page = _FakePage(_FakeHandle(_sequence(PLAYWRIGHT_TARGET_CLOSED_ERROR())))

    with pytest.raises(PLAYWRIGHT_TARGET_CLOSED_ERROR) as raised:
        await element_call(page, "resolve", "e1", {})
    assert "take a new snapshot" not in str(raised.value)


async def test_a_page_that_never_answers_reports_the_operation_budget() -> None:
    async def never(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(3600)

    handle = _FakeHandle(lambda _: None)
    handle.evaluate = never  # type: ignore[method-assign]
    page = _FakePage(handle)

    with pytest.raises(TimeoutError) as raised:
        await page.elements.call("resolve", {"id": "e1"}, timeout=0.05)
    assert "page script did not answer within" in str(raised.value)


async def test_a_wedged_dispose_does_not_wedge_the_whole_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disposal runs under the lock, so an unbounded await there is a permanent hang."""
    monkeypatch.setattr(registry_module, "DISPOSE_TIMEOUT", 0.05)
    page = _FakePage(
        _FakeHandle(_sequence(DriverError(DEAD_CONTEXT)), hang_dispose=True),
        _FakeHandle(_sequence({"ok": True})),
    )

    with pytest.raises(DeadContextError):
        await asyncio.wait_for(page.elements.call("resolve", {"id": "e1"}), 3.0)
    assert await asyncio.wait_for(page.elements.call("resolve", {"id": "e1"}), 3.0) == {"ok": True}


_OP_CASES: list[tuple[str, dict[str, Any], Callable[[_FakePage], Any]]] = [
    ("capture", {"capture": INTERNAL}, lambda page: capture_snapshot(page)),
    ("resolve", {"resolve": INTERNAL}, lambda page: resolve(page, "e1", deadline=0.0)),
    ("locate", {"locate": INTERNAL}, lambda page: bind_selector(page, "#x", deadline=0.0)),
    ("scrollTo", {"scrollTo": INTERNAL}, lambda page: scroll_uid(page, "e1")),
    (
        "prepareFill",
        {"resolve": _hit("text"), "prepareFill": INTERNAL},
        lambda page: fill_field(page, "e1", "hello"),
    ),
    (
        "selectOptions",
        {"resolve": _hit("select"), "selectOptions": INTERNAL},
        lambda page: fill_field(page, "e1", "Apple"),
    ),
    (
        "selectOption",
        {
            "resolve": _hit("select"),
            "selectOptions": {"options": [{"value": "a", "label": "Apple"}]},
            "selectOption": INTERNAL,
        },
        lambda page: fill_field(page, "e1", "Apple"),
    ),
    ("setFiles", {"setFiles": INTERNAL}, lambda page: set_files(page, "e1", __file__)),
    (
        "evaluate",
        {"evaluate": {"ok": False, **INTERNAL}},
        lambda page: evaluate_with_uids(page, "(el) => el.tagName", ["e1"]),
    ),
]


@pytest.mark.parametrize(("op", "replies", "run"), _OP_CASES, ids=[case[0] for case in _OP_CASES])
async def test_an_internal_failure_names_the_operation_that_broke(
    op: str, replies: dict[str, Any], run: Callable[[_FakePage], Any]
) -> None:
    """A bug in our own page script is the one case where the op name is everything."""
    page = _FakePage(_FakeHandle(_per_op(replies)))

    with pytest.raises(ValueError) as raised:
        await run(page)

    assert str(raised.value) == f"page script failed in '{op}': {INTERNAL['msg']}"
