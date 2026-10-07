"""The daemon's record of which proxies are still connected to it.

Every proxy renews a lease on a timer for as long as it runs, and releases it when it
exits cleanly. A proxy that dies without releasing simply stops renewing, and its lease
expires a few intervals later. The idle watchdog keeps the daemon alive while any lease
is live, and counts its TTL from :meth:`LeaseTable.vacated_at`: the moment the last
proxy left, not the last time one happened to send a request.

Pure bookkeeping on an injected clock, so the rules are testable without a daemon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from camoufox_mcp.daemon.errors import LeaseClosedError, LeaseLimitError

if TYPE_CHECKING:
    from collections.abc import Callable

# A proxy chooses its own expiry (3 of its renewal intervals), within these bounds: a
# ttl below 1 s would expire between 2 renewals of any sane interval, and one above
# 15 min would keep a dead proxy's daemon alive long past the user's TTL.
MIN_LEASE_TTL_S = 1.0
MAX_LEASE_TTL_S = 900.0
MAX_LEASES = 256


@dataclass
class _Lease:
    expires_at: float
    ttl_s: float


class LeaseTable:
    """Live proxy leases, keyed by the random id each proxy picks for itself."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._leases: dict[str, _Lease] = {}
        self._vacated_at: float | None = None
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once the daemon has decided to exit: no lease is granted any more."""
        return self._closed

    def close(self) -> None:
        """Refuse every later grant. Called in the same step that decides to exit, so
        no proxy can be told this daemon is alive once it has committed to going."""
        self._closed = True

    def grant(self, lease_id: str, ttl_s: float) -> float:
        """Create or renew ``lease_id`` for ``ttl_s`` (clamped); return the granted ttl.

        Raises:
            LeaseClosedError: the table was closed because the daemon is exiting.
            LeaseLimitError: a new id while :data:`MAX_LEASES` leases are already live.
        """
        if self._closed:
            raise LeaseClosedError("the daemon is shutting down")
        self._prune()
        if lease_id not in self._leases and len(self._leases) >= MAX_LEASES:
            raise LeaseLimitError(f"the daemon already holds {MAX_LEASES} live leases")
        granted = min(max(ttl_s, MIN_LEASE_TTL_S), MAX_LEASE_TTL_S)
        self._leases[lease_id] = _Lease(expires_at=self._clock() + granted, ttl_s=granted)
        self._vacated_at = None
        return granted

    def release(self, lease_id: str) -> bool:
        """Drop ``lease_id`` at once; False when it was not live."""
        self._prune()
        if self._leases.pop(lease_id, None) is None:
            return False
        if not self._leases:
            self._vacated_at = self._clock()
        return True

    def live_count(self) -> int:
        """How many leases have neither expired nor been released."""
        self._prune()
        return len(self._leases)

    def vacated_at(self) -> float | None:
        """When the table last became empty, or None while leases are live or none ever was.

        That is the release instant of the last lease, or the expiry instant of the last
        one to lapse, never the time it was last renewed: a proxy killed mid-interval
        still leaves the daemon its whole TTL, counted from the moment it stopped counting.
        """
        self._prune()
        return None if self._leases else self._vacated_at

    def refresh_all(self) -> None:
        """Restart every lease's expiry from now, each at its own granted ttl.

        The grace after a machine suspend: the proxies were frozen too and could not
        renew, so each gets 1 full ttl to send its first renewal after the wake.
        """
        now = self._clock()
        for lease in self._leases.values():
            lease.expires_at = now + lease.ttl_s

    def _prune(self) -> None:
        now = self._clock()
        expired = [key for key, lease in self._leases.items() if lease.expires_at <= now]
        if not expired:
            return
        last_expiry = max(self._leases[key].expires_at for key in expired)
        for key in expired:
            del self._leases[key]
        if not self._leases:
            previous = float("-inf") if self._vacated_at is None else self._vacated_at
            self._vacated_at = max(previous, last_expiry)
