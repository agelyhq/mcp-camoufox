"""Nothing this server starts is left abandoned: not a handle, not a protocol reply.

Two defects with one shape. The element store dropped its handle on every
navigation without ever releasing it, so the release path was reachable only on a tab
that had not navigated since its last operation; it now retires the handle and drains
it under the lock every operation takes. An operation that ran out of budget left its
protocol reply live and unowned, and the driver discards a late answer only when the
reply future is cancelled, which it only does when the task that issued the call is
cancelled: every run of the waiting suite ended on "Future exception was never
retrieved", which is how a team learns to ignore warnings.

The third defect of the same family, an injected bundle reaching for page globals by
name at call time, lives in ``tests/test_injected_globals.py``.
"""

from __future__ import annotations

import asyncio
import gc
from typing import TYPE_CHECKING, Any

import pytest

from camoufox_mcp.sessions.errors import PLAYWRIGHT_TARGET_CLOSED_ERROR
from tests.fakes import FakeHandle, FakePage
from tests.helpers import PROFILE, extract_uid, isolate_camoufox_env, open_page, tool_text
from tests.waits import poll_until

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from fastmcp import Client, FastMCP

    from camoufox_mcp.tools._base import ToolDeps

UNREAD = "never retrieved"

# How long an abandoned protocol reply is given to arrive and be reported. This is a
# detection window, not a settle time: it can only fail open, so it is driven rather
# than slept through, and the assertion below fires the instant a report lands.
_REPORT_WINDOW_S = 0.5


@pytest.fixture
def deps(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> ToolDeps:
    """The same dependencies the server runs on, reachable for the live session."""
    isolate_camoufox_env(monkeypatch, data_dir)

    from camoufox_mcp.bootstrap import build_deps
    from camoufox_mcp.config import ServerConfig

    return build_deps(ServerConfig.from_env())


@pytest.fixture
async def loop_reports() -> AsyncIterator[list[str]]:
    """Every message asyncio hands to the running loop's exception handler.

    "Future exception was never retrieved" is raised nowhere: the future's destructor
    reports it here, which makes this handler the only structural observable for it.
    The previous handler still runs, so the report also keeps reaching the captured
    output the test asserts on.
    """
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    messages: list[str] = []

    def record(running_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        messages.append(str(context.get("message", "")))
        if previous is None:
            running_loop.default_exception_handler(context)
        else:
            previous(running_loop, context)

    loop.set_exception_handler(record)
    try:
        yield messages
    finally:
        loop.set_exception_handler(previous)


@pytest.fixture
def mcp_server(deps: ToolDeps) -> FastMCP:
    from camoufox_mcp.bootstrap import build_server

    return build_server(deps.config, deps)


async def test_a_retired_handle_is_released_by_the_next_operation() -> None:
    """A navigation must not cost a handle: the store owns it until it is released."""
    first, second = FakeHandle(), FakeHandle()
    page = FakePage(first, second)

    await page.elements.call("resolve", {"id": "e1"})
    page.elements.forget()
    assert first.disposed == 0, "forget() does I/O, and a page event cannot await"

    await page.elements.call("resolve", {"id": "e1"})

    assert first.disposed == 1
    assert second.disposed == 0
    assert page.built == 2


async def test_a_retired_handle_is_released_when_the_tab_closes() -> None:
    """The close is the last chance to release, and it must reach a retired handle."""
    handle = FakeHandle()
    page = FakePage(handle)

    await page.elements.call("resolve", {"id": "e1"})
    page.elements.forget()
    await page.elements.dispose()

    assert handle.disposed == 1


async def test_a_release_never_fails_the_operation_that_triggers_it() -> None:
    """Releasing is best effort: the context it belonged to is usually already gone."""
    doomed = FakeHandle(dispose_error=PLAYWRIGHT_TARGET_CLOSED_ERROR())
    page = FakePage(doomed, FakeHandle())

    await page.elements.call("resolve", {"id": "e1"})
    page.elements.forget()

    assert await page.elements.call("resolve", {"id": "e1"}) == {"ok": True}
    assert doomed.disposed == 1


async def test_a_release_is_never_handed_a_handle_still_in_use() -> None:
    """The drain runs under the store lock, so it cannot overtake a live operation.

    The ordering is decided by the shared log, never by a clock: the slow operation
    appends "operation ended" and the drain appends "released", so a drain that
    overtook a live operation inverts the pair. The 2 mid-flight assertions establish
    that the second call really is parked behind the first, without which the whole
    scenario degrades into 2 sequential calls and proves nothing.
    """
    started = asyncio.Event()
    finish = asyncio.Event()
    order: list[str] = []

    async def slowly(_payload: dict[str, Any]) -> Any:
        started.set()
        await finish.wait()
        order.append("operation ended")
        return {"ok": True}

    slow = FakeHandle(slowly, order=order)
    page = FakePage(slow, FakeHandle())

    inflight = asyncio.ensure_future(page.elements.call("resolve", {"id": "e1"}))
    await started.wait()

    page.elements.forget()
    queued = asyncio.ensure_future(page.elements.call("resolve", {"id": "e1"}))
    # One scheduler turn is all the queued task needs to reach its first await, the
    # store lock. Getting PAST it is what it must not have done, and building a
    # second handle is the first thing it would do if it had.
    await asyncio.sleep(0)
    assert page.built == 1, "the queued call got past the store lock instead of parking on it"
    assert slow.disposed == 0, "the handle was released while an operation still held it"

    finish.set()
    await inflight
    await queued
    assert slow.disposed == 1
    assert order == ["operation ended", "released"], order


async def test_an_expired_operation_leaves_no_unread_error_behind(
    client: Client,
    flask_server: str,
    deps: ToolDeps,
    loop_reports: list[str],
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A budget that expires must not leave the driver holding an answer for nobody.

    Proving an absence needs a window, so the window is driven instead of slept
    through: the loop below collects garbage and lets the loop deliver the driver's
    late answer until a report appears, and the assertion fires on the first one. The
    reports are read from the loop's exception handler rather than only from captured
    output, so the test cannot go green merely because the report landed a
    millisecond after a fixed nap ended. The handler still forwards to the default
    one, because the printed line is what actually costs the team.
    """
    await open_page(client, f"{flask_server}/click")
    session = deps.sessions.get(PROFILE)
    assert session is not None

    with pytest.raises(TimeoutError):
        await session.active_page.elements.call(
            "evaluate", {"src": "() => new Promise(() => {})", "ids": []}, timeout=0.3
        )

    # The abandoned answer arrives only when the tab goes, and it is reported only
    # when the reply is collected, so both must happen before the assertion.
    await deps.sessions.close_session(PROFILE)
    await _driven_until(lambda: any(UNREAD in line for line in loop_reports))

    assert not [line for line in loop_reports if UNREAD in line], loop_reports
    assert UNREAD not in caplog.text, caplog.text
    assert UNREAD not in capfd.readouterr().err


async def _driven_until(reported: Callable[[], bool]) -> None:
    """Run the loop and the collector until a report lands, or the window elapses.

    A destructor only runs once the reply is collected, so every turn has to include
    a ``gc.collect()``; and the driver's late answer arrives over a socket, so the
    loop must actually get to poll it.
    """

    async def collect() -> bool:
        gc.collect()
        return reported()

    await poll_until(collect, bool, deadline=_REPORT_WINDOW_S, interval=0.01)


async def test_a_tab_survives_the_navigations_that_retire_its_handles(
    client: Client, flask_server: str, capfd: pytest.CaptureFixture[str]
) -> None:
    """The release runs against a context a navigation already destroyed, and is silent."""
    for _ in range(3):
        await open_page(client, f"{flask_server}/click")
        snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
        uid = extract_uid(snap, "Click me")
        clicked = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
        assert clicked.startswith("Clicked <button>"), clicked

    assert "Error" not in capfd.readouterr().err
