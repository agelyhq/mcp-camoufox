"""The lease one proxy holds on the shared daemon, for as long as the proxy runs.

Two jobs ride on the same renewal. It keeps the daemon from idling out under a proxy
whose user is merely silent, and it tells the proxy which daemon PROCESS is answering.
The daemon is stateless over HTTP, so a replacement behind this proxy's back fails
nothing any more: the very next call would quietly land on a fresh daemon that owns
none of the browsers the conversation was using. The identity in each renewal is what
lets the proxy say so, exactly once.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

import anyio

from camoufox_mcp.daemon.errors import LeaseRejectedError
from camoufox_mcp.daemon.lease_client import UNKNOWN, Alive

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from camoufox_mcp.daemon.identity import DaemonInstance
    from camoufox_mcp.daemon.lease_client import Probe

logger = logging.getLogger(__name__)

# A lease outlives 2 missed renewals and expires on the third.
LEASE_TTL_FACTOR = 3
# The heartbeat wakes at least this often to compare clocks, so a renewal follows a
# machine resume within these seconds even where the monotonic clock froze.
WAKE_POLL_S = 5.0


class LeaseChannel(Protocol):
    """What :class:`DaemonLease` needs from the wire (see ``LeaseClient``)."""

    async def renew(self) -> Probe: ...

    async def release(self) -> None: ...

    async def aclose(self) -> None: ...


class DaemonLease:
    """Holds this proxy's lease and remembers which daemon instance it is bound to."""

    def __init__(
        self,
        channel: LeaseChannel,
        interval_s: float,
        *,
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._channel = channel
        self._interval_s = interval_s
        self._mono = mono
        self._wall = wall
        self._sleep = sleep
        self._bound: DaemonInstance | None = None
        self._notice_pending = False
        self._renewed_mono = float("-inf")
        self._renewed_wall = float("-inf")

    @property
    def bound(self) -> DaemonInstance | None:
        """The daemon instance this proxy currently talks to, None until one is proven.

        A request remembers the value it started under: a different value later means
        the daemon holding that request is gone, whoever noticed first.
        """
        return self._bound

    async def check(self) -> Probe:
        """Renew now; what the renewal proves. A changed instance raises the notice."""
        try:
            probe = await self._channel.renew()
        except LeaseRejectedError:
            logger.warning("The daemon refused this proxy's lease", exc_info=True)
            return UNKNOWN
        if isinstance(probe, Alive):
            self._observe(probe.instance)
            self._renewed_mono, self._renewed_wall = self._mono(), self._wall()
        return probe

    def take_notice(self) -> bool:
        """Read and clear the pending notice, so exactly one caller reports a replacement.

        No await between the read and the clear: on one event loop that is atomic.
        """
        pending, self._notice_pending = self._notice_pending, False
        return pending

    def raise_notice(self) -> None:
        """Keep a restart pending for the next call that can report it to the model."""
        self._notice_pending = True

    async def adopt_current(self) -> None:
        """Bind to the daemon this proxy just respawned, without raising a notice.

        The respawn path reports the restart itself, so a notice would report it twice.
        A renewal that proves nothing (the fresh daemon is busy) unbinds instead of
        keeping the dead instance: the next ``Alive`` then binds silently rather than
        reading as a second replacement.
        """
        if not isinstance(await self.check(), Alive):
            self._bound = None
        self._notice_pending = False

    async def heartbeat(self) -> None:
        """Renew every interval until cancelled; never respawns, never raises.

        Elapsed time is measured on both clocks and the larger wins: after a suspend
        the wall clock has jumped even where the monotonic one did not count the sleep,
        so the first wake poll renews at once instead of a whole interval later.
        """
        while True:
            await self._sleep(min(self._interval_s, WAKE_POLL_S))
            if not self._due():
                continue
            probe = await self.check()
            if not isinstance(probe, Alive):
                logger.debug("Lease renewal got no answer (%s); retrying", probe)

    @contextlib.asynccontextmanager
    async def lifespan(self, _server: Any) -> AsyncIterator[dict[str, Any]]:
        """The proxy server's lifespan: lease on start, heartbeat while up, release on exit.

        A lifespan rather than a task started by hand, because it is the one hook that
        runs inside the proxy's own event loop, both under ``run(transport="stdio")`` and
        under an in-memory client, so the tests exercise the real heartbeat.
        """
        await self.check()
        heartbeat = asyncio.create_task(self.heartbeat())
        try:
            yield {}
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            with anyio.CancelScope(shield=True):
                await self._channel.release()
                await self._channel.aclose()

    def _observe(self, instance: DaemonInstance) -> None:
        if self._bound is None:
            self._bound = instance
            return
        if instance != self._bound:
            logger.warning("Daemon %s was replaced by %s", self._bound, instance)
            self._bound = instance
            self._notice_pending = True

    def _due(self) -> bool:
        since_mono = self._mono() - self._renewed_mono
        since_wall = self._wall() - self._renewed_wall
        return max(since_mono, since_wall) >= self._interval_s
