"""Every wait in the suite, driven by a condition rather than by a duration.

A test depends on an appearance or on a fixed result, never on a nap. One primitive
polls a probe until an answer is accepted and takes a deadline only as a guardrail: a
slow runner then costs extra polls instead of producing a false green (the condition
was asserted before it could hold) or a false red (the machine was slower than a
hard-coded sleep).

Three kinds of observable, three entry points on top of that primitive:

* page-side conditions (a counter, a scroll position, a rendered node, a status text)
  go through the product's own ``wait_for(condition='predicate')``, which polls at 50 ms
  and reports the predicate's last value on expiry;
* monitor-side conditions (console messages, network entries) must poll the listing
  tool itself, because those buffers are fed by asynchronous protocol events that a
  page-side wait cannot observe;
* process-side conditions (a daemon that must be gone, an advert that must be
  unlinked) are synchronous, and use :func:`poll_until_sync`.

Two tool pollers, because expiry means two different things. ``poll_tool_until`` owns
the verdict and raises with the last output as its diagnostic; ``poll_tool_or_last``
hands the last output back so the caller's own assertion stays the verdict.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING, TypeVar

from tests.helpers import tool_text

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import Client

T = TypeVar("T")

# Generous on purpose: it bounds a hung tool, it does not encode how fast the runner is.
DEADLINE_S = 15.0
INTERVAL_S = 0.25

# "[3] GET 200 fetch http://127.0.0.1:5610/api/data"
_ENTRY = re.compile(
    r"^\[(?P<reqid>\d+)\] (?P<method>\S+) (?P<status>\S+) (?P<type>\S+) (?P<url>\S+)$"
)


async def poll_until(
    probe: Callable[[], Awaitable[T]],
    accept: Callable[[T], bool],
    *,
    deadline: float = DEADLINE_S,
    interval: float = INTERVAL_S,
) -> tuple[T, bool]:
    """Call ``probe`` until ``accept`` takes its answer; return that answer and whether
    it was accepted.

    The condition is the test and the deadline is only the guardrail, so expiry is
    reported rather than raised on: a caller that owns the verdict raises on the
    ``False``, and a caller whose own assertion is the verdict simply uses the value.
    """
    end = time.monotonic() + deadline
    while True:
        answer = await probe()
        if accept(answer):
            return answer, True
        if time.monotonic() >= end:
            return answer, False
        await asyncio.sleep(interval)


def poll_until_sync(
    condition: Callable[[], bool], *, deadline: float, interval: float = 0.1
) -> bool:
    """Synchronous :func:`poll_until`, for process-side conditions off the event loop."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(interval)
    return condition()


async def poll_tool_until(
    client: Client,
    name: str,
    args: dict[str, object],
    accept: Callable[[str], bool],
    *,
    describe: str,
    deadline: float = DEADLINE_S,
    interval: float = INTERVAL_S,
) -> str:
    """Call ``name`` until ``accept`` takes its output, then return that output.

    On expiry the last output is part of the failure, because it is the diagnostic a
    blind sleep destroys.
    """
    text, accepted = await poll_until(
        lambda: _call(client, name, args), accept, deadline=deadline, interval=interval
    )
    if not accepted:
        msg = f"{describe} within {deadline:g}s. Last {name} output:\n{text}"
        raise AssertionError(msg)
    return text


async def poll_tool_or_last(
    client: Client,
    name: str,
    args: dict[str, object],
    accept: Callable[[str], bool],
    *,
    deadline: float = DEADLINE_S,
    interval: float = INTERVAL_S,
) -> str:
    """Call ``name`` until ``accept`` takes its output, then return that output.

    On expiry the last text is returned rather than raised on, so the caller's own
    assertion is what fails, with the full tool output as its message.
    """
    text, _ = await poll_until(
        lambda: _call(client, name, args), accept, deadline=deadline, interval=interval
    )
    return text


async def poll_tool_text(
    client: Client,
    name: str,
    args: dict[str, object],
    needle: str,
    *,
    deadline: float = DEADLINE_S,
) -> str:
    """Call a tool until ``needle`` appears in its text, then return that text."""
    return await poll_tool_or_last(
        client, name, args, lambda text: needle in text, deadline=deadline
    )


async def wait_predicate(
    client: Client, profile: str, expression: str, *, timeout_ms: int = 15000
) -> None:
    """Wait for a page predicate through the product's own ``wait_for`` tool.

    The success string is asserted here, so an expiry fails the calling test with
    ``wait_for``'s own diagnostic (the predicate's last value), which is exactly what a
    fixed sleep destroys.
    """
    result = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": profile,
                "condition": "predicate",
                "expression": expression,
                "timeout": timeout_ms,
            },
        )
    )
    assert result == "Condition met: predicate", result


def completed_entry(listing: str, url_fragment: str) -> str | None:
    """The listing line whose URL contains ``url_fragment`` and already has a status.

    ``None`` while the request is absent or still "pending", which is the condition a
    test asserting on a status code has to wait for.
    """
    for line in listing.splitlines():
        match = _ENTRY.match(line.strip())
        if match and url_fragment in match["url"] and match["status"] != "pending":
            return line
    return None


def reqid_for(listing: str, url_fragment: str) -> int:
    """The reqid of the completed request whose URL contains ``url_fragment``.

    Aiming detail assertions at "the first bracketed id in the listing" pointed them at
    whatever request happened to land first on the tab (a favicon probe, an asset added
    to the page later), which silently retargets the whole test.
    """
    line = completed_entry(listing, url_fragment)
    if line is None:
        msg = f"no completed request matching {url_fragment!r} in listing:\n{listing}"
        raise AssertionError(msg)
    match = _ENTRY.match(line.strip())
    assert match is not None
    return int(match["reqid"])


async def _call(client: Client, name: str, args: dict[str, object]) -> str:
    return tool_text(await client.call_tool(name, args))
