"""The idle watchdog's exit rule on fake clocks: a live lease, a suspend and the TTL
interact over hours of simulated time, which no real daemon reaches in bounded time,
so these are focused tests on pure logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from camoufox_mcp.daemon.leases import LeaseTable
from camoufox_mcp.daemon.lifecycle import ActivityState, idle_watchdog
from tests.fake_clocks import Clocks

_TICK_S = 15.0  # the watchdog's check interval for a 60 s TTL
_FIRST_CHECK_PAST_TTL_S = 75.0  # 60 s is not past the TTL; the next tick is


@dataclass
class _Sessions:
    count: int = 0

    def active_count(self) -> int:
        return self.count


@dataclass
class _Config:
    daemon_ttl_seconds: int = 60


async def _run_watchdog(clock: Clocks, table: LeaseTable, steps: list[Any]) -> float:
    """Run the watchdog over ``steps`` (one per check, then plain ticks); the exit time."""
    state = ActivityState(clock=lambda: clock.mono)
    exits: list[float] = []
    ticks = 0

    async def sleep(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        assert ticks < 100, "the watchdog never exited"
        (steps.pop(0) if steps else lambda: clock.advance(_TICK_S))()

    def terminate(_delay: float) -> None:
        exits.append(clock.mono)

    await idle_watchdog(
        _Config(),  # type: ignore[arg-type]
        _Sessions(),  # type: ignore[arg-type]
        state,
        table,
        mono=lambda: clock.mono,
        wall=lambda: clock.wall,
        sleep=sleep,
        terminate=terminate,
    )
    assert table.closed, "the watchdog exited without refusing new leases first"
    assert len(exits) == 1
    return exits[0]


async def test_watchdog_never_exits_under_a_live_lease() -> None:
    """Idle far past the TTL, but leased: it waits, then counts the TTL from the release."""
    clock = Clocks()
    table = LeaseTable(clock=lambda: clock.mono)
    table.grant("a", 900.0)
    released_at: list[float] = []
    steps: list[Any] = [lambda: clock.advance(_TICK_S) for _ in range(10)]  # 150 s idle

    def release() -> None:
        clock.advance(_TICK_S)
        released_at.append(clock.mono)
        table.release("a")

    steps.append(release)

    exited_at = await _run_watchdog(clock, table, steps)
    assert exited_at == released_at[0] + _FIRST_CHECK_PAST_TTL_S


@pytest.mark.parametrize("monotonic_froze", [True, False])
async def test_watchdog_forgives_a_suspend(monotonic_froze: bool) -> None:
    """After a suspend every lease restarts its ttl from the wake, before the TTL counts.

    Without that grace the frozen-clock case exits 1 tick early (at the lease's original
    expiry plus the TTL) and the counted-sleep case exits at once on the wake.
    """
    clock = Clocks()
    table = LeaseTable(clock=lambda: clock.mono)
    table.grant("a", 90.0)
    steps: list[Any] = [
        lambda: clock.advance(_TICK_S),
        lambda: clock.advance(7200, suspended=monotonic_froze),
    ]
    woke_at = clock.mono + _TICK_S + (0 if monotonic_froze else 7200)

    exited_at = await _run_watchdog(clock, table, steps)
    # The lease, refreshed at the wake, lapses 90 s later and is never renewed (its
    # proxy died in the sleep); the exit is the first check past the TTL after that.
    assert exited_at == woke_at + 90 + _FIRST_CHECK_PAST_TTL_S
