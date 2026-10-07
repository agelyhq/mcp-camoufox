"""Telling a machine suspend apart from idle time, on every platform's clocks.

A suspended machine freezes the proxies with the daemon, so on wake every lease looks
overdue although no proxy left. What the clocks report depends on the platform:
CLOCK_MONOTONIC on Linux and macOS stops during a suspend while the wall clock does not,
and Windows' monotonic clock (like CLOCK_BOOTTIME, or a process stopped by SIGSTOP)
keeps counting, so the gap shows up as one loop tick far longer than it should be.
Either signature counts as a suspend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_SLACK_S = 5.0


class SuspendDetector:
    """Report whether the process was frozen since the previous :meth:`tick`."""

    def __init__(
        self,
        interval_s: float,
        *,
        mono: Callable[[], float],
        wall: Callable[[], float],
        slack_s: float = DEFAULT_SLACK_S,
    ) -> None:
        self._interval_s = interval_s
        self._mono = mono
        self._wall = wall
        self._slack_s = slack_s
        self._last_mono = mono()
        self._last_wall = wall()

    def tick(self) -> bool:
        """True when the time since the last tick shows a suspend or a frozen process.

        Wall time far ahead of monotonic time is a suspend the monotonic clock did not
        count. A monotonic step far longer than the tick interval is one it did count.
        A wall clock stepped BACKWARD (NTP) shows neither and is ignored; one stepped
        forward by more than the slack reads as a suspend, which only grants the leases
        1 extra ttl.
        """
        mono, wall = self._mono(), self._wall()
        mono_delta = mono - self._last_mono
        wall_delta = wall - self._last_wall
        self._last_mono, self._last_wall = mono, wall
        uncounted = wall_delta - mono_delta > self._slack_s
        overlong = mono_delta > self._interval_s + self._slack_s
        return uncounted or overlong
