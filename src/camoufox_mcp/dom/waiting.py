"""The one clock that bounds every wait in this package: every budget, and the poll.

Nothing waits inside the page: an injected operation is always one synchronous turn,
and the budget that bounds it lives here, in Python. That is true of the per-operation
ceilings below as much as of ``ACTION_DEADLINE``, so they are declared together rather
than scattered across the module that happens to spend each one.

``ACTION_DEADLINE`` is what replaced the driver's own auto-wait when the selector path
stopped going through it, and it is deliberately shorter than the 30000 ms the driver
retried for. A wrong selector is far more common than a page that renders 30 s late,
and under the old budget every wrong selector cost the agent 30 s before it learned
anything. A short budget only becomes a trap when it is silent, which is why the
expiry messages in ``identity.py`` name the budget they spent.

A caller that genuinely needs longer waits for the element first, with
``wait_for(condition='selector')``, whose timeout is per call and reaches the same
poll through ``locate_visible``. So the wait is bounded, adjustable and reachable, and
no tool pays a parameter for it.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# Budget for the poll inside a single action (click, fill, upload, screenshot).
ACTION_DEADLINE = 5.0
_INTERVAL = 0.05

# Hard ceiling on one page operation. Page evaluation carries no deadline at any
# layer, so without this a wedged content process hangs the call forever.
OP_TIMEOUT = 15.0
# The ``evaluate`` operation only: the caller's own script runs inside it.
EVAL_TIMEOUT = 30.0
# ``setFiles`` only: the file bytes cross the protocol base64-encoded.
UPLOAD_TIMEOUT = 60.0
# Releasing a handle is a single protocol round trip, so it normally returns at once
# even on a destroyed execution context. It is bounded anyway because it runs under
# the registry's lock, and an unbounded await there would wedge every later operation
# on the tab.
DISPOSE_TIMEOUT = 5.0


def render_deadline(deadline: float) -> str:
    """The budget as it reads in an error message: ``5s``, ``0.5s``, never ``5.0s``."""
    return f"{deadline:g}s"


class PollExpiredError(Exception):
    """Internal: the poll ran out of budget. Carries the last probe result."""

    def __init__(self, last: Any) -> None:
        self.last = last
        super().__init__("the poll ran out of budget")


async def poll_until[T](
    probe: Callable[[], Awaitable[T]],
    accept: Callable[[T], bool],
    *,
    deadline: float,
    interval: float = _INTERVAL,
) -> T:
    """Run ``probe`` every ``interval`` until ``accept`` says yes or time runs out.

    This is the only waiting mechanism in this package. Nothing waits inside the
    page: an injected operation is always one synchronous turn, and the clock that
    bounds it lives here, in Python.

    Raises ``PollExpiredError`` carrying the last probe result, so the caller can render
    a specific error (which overlay, which selector, what a predicate last returned)
    instead of a bare timeout.
    """
    end = time.monotonic() + deadline
    while True:
        last = await probe()
        if accept(last):
            return last
        if time.monotonic() >= end:
            raise PollExpiredError(last)
        await asyncio.sleep(interval)
