"""A pair of fake clocks for the pure lease and watchdog rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Clocks:
    mono: float = 1000.0
    wall: float = 5_000_000.0

    def advance(self, seconds: float, *, suspended: bool = False) -> None:
        """Move time on; a suspend moves only the wall clock (Linux/macOS monotonic)."""
        self.wall += seconds
        if not suspended:
            self.mono += seconds
