from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine


async def bounded[T](work: Coroutine[Any, Any, T], timeout: float) -> T:
    """Await ``work`` under a real clock, as a task of its own.

    No Playwright call carries a deadline of its own, and Firefox can stop answering
    Juggler while its process stays alive (see ``sessions/launch.py``), so every await
    that would otherwise be unbounded goes through here.

    The task is as much the point as the clock: the driver forwards the cancellation
    of the task that issued a protocol call to that call's own reply future, and only
    a cancelled reply future makes it discard an answer that arrives late. Awaited
    inline instead, an expired budget leaves the reply live and unowned: when the tab
    is later closed the driver answers it with a target-closed error that nobody is
    left to read, and the interpreter reports "Future exception was never retrieved"
    at collection time, on a run that otherwise passed.
    """
    task = asyncio.ensure_future(work)
    return await asyncio.wait_for(task, timeout)
