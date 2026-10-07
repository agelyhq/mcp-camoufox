"""Bringing the daemon back when it dies in the middle of a conversation.

The daemon is ensured once, when a proxy starts. Without this module a daemon that
dies at call 12 takes calls 13 onward with it, each one failing on a bare
``Connection refused``. Here every failed request asks the control channel whether the
daemon is still there, respawns it once if it is not, and answers the caller with the
only honest outcome: this call did not complete, the browser sessions the dead daemon
held are gone, and the next call will reach a fresh daemon.

A daemon that dies mid-request raises nothing at all. The streamable-HTTP response is
never written, the connection stays open from the client's side, and the transport read
timeout is far longer than any conversation can wait: measured, the call was still
pending 180 s after the kill. So an outstanding request is also watched from the
outside, by probing the control channel on a timer and cancelling the call once the
daemon is proven gone.

The respawn is deliberately NOT a replay of the failed request. A replay would either
re-run an action the dying daemon may already have performed, or land on a daemon that
owns no browser and fail again for a second reason. The TTL accounting stays exact for
the same reason: the daemon counts in-flight requests, and no request is ever sent twice.
A cancellation cannot strand that counter either, since the only request ever cancelled
here is one whose daemon no longer exists.

A daemon can also be replaced behind this proxy's back: it exits (idle TTL, crash) and
another proxy sharing the address spawns a new one before this proxy notices. The new
daemon answers ``/health``, so liveness alone calls every later failure genuine, while
the cached backend session id belongs to the old process and draws a 404 on each call
(surfacing as "Unknown tool"). The daemon instance the backend session was opened
against is therefore remembered, and a failure against a different live instance is
handled like a death: drop the stale backend, report once, and the next call works.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx
import mcp.types
from fastmcp.server.middleware import Middleware
from mcp.shared.exceptions import McpError

from camoufox_mcp.daemon.errors import DaemonError
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp.server.providers.proxy import StatefulProxyClient

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.daemon.endpoint import DaemonEndpoint

logger = logging.getLogger(__name__)

# Long enough that a burst of concurrent failures shares one respawn, short enough
# that a second, genuinely later crash is still repaired.
_RESPAWN_COOLDOWN_S = 5.0

# How often an outstanding request checks that its daemon still exists, and how many
# consecutive checks must agree before the call is cancelled. Two, not one, because a
# Unix socket whose accept backlog is momentarily full also refuses connections; that
# clears in milliseconds, so a second refusal a whole interval later is real.
WATCH_INTERVAL_S = 2.0
DEATH_CONFIRMATIONS = 2
_LIVENESS_TIMEOUT_S = 2.0

# One daemon process: its pid plus its start time, so a recycled pid is still told apart.
DaemonInstance = tuple[object, object]


class _DaemonVanishedError(Exception):
    """The daemon holding this request disappeared while it was outstanding."""


def proven_gone(config: ServerConfig, endpoint: DaemonEndpoint) -> bool:
    """True only on positive proof that nothing is listening on the control address.

    Deliberately not :func:`probe_health`, which folds every failure into ``None`` and
    so cannot tell a dead daemon from one whose event loop is briefly busy (a cold
    browser launch does block it). Cancelling on a slow answer would kill exactly the
    healthy long call this watchdog must leave alone, so only 2 outcomes count as
    proof: no advertised address at all, and a refused connection.
    """
    conn = endpoint.resolve(config)
    if conn is None:
        return True
    try:
        with endpoint.sync_client(conn, timeout=_LIVENESS_TIMEOUT_S) as client:
            client.get("/health")
    except httpx.ConnectError:
        return True
    except (httpx.HTTPError, OSError):
        return False
    return False


RESTARTED_MESSAGE = (
    "the shared camoufox daemon died and has been restarted. This call did not "
    "complete, and every browser session the old daemon held is gone: the profiles are "
    "intact on disk, the open pages are not. Run the call again to start a fresh session."
)
UNRECOVERED_MESSAGE = (
    "the shared camoufox daemon died and could not be restarted (see daemon.log in the "
    "data dir). This call did not complete, and every browser session it held is gone."
)


class DaemonRecovery:
    """Serialized, bounded respawn of the daemon this proxy talks to."""

    def __init__(self, config: ServerConfig, endpoint: DaemonEndpoint) -> None:
        self._config = config
        self._endpoint = endpoint
        self._lock = asyncio.Lock()
        # -inf, not 0.0: time.monotonic() counts from boot, so a proxy started
        # seconds after boot would otherwise see its first respawn as a duplicate.
        self._last_attempt = float("-inf")

    async def instance(self) -> DaemonInstance | None:
        """The daemon process answering ``/health`` right now, or None when none does."""
        health = await asyncio.to_thread(probe_health, self._config, self._endpoint)
        if health is None:
            return None
        return (health.get("pid"), health.get("started_at"))

    async def is_live(self) -> bool:
        """True when the control channel still answers ``/health``."""
        return await self.instance() is not None

    async def is_gone(self) -> bool:
        """True when the daemon is proven absent (see :func:`proven_gone`)."""
        return await asyncio.to_thread(proven_gone, self._config, self._endpoint)

    async def respawn(self) -> bool:
        """Ensure a daemon is listening again, at most once per cooldown window."""
        async with self._lock:
            if time.monotonic() - self._last_attempt < _RESPAWN_COOLDOWN_S:
                # A concurrent failure just respawned; report that one's outcome
                # instead of spawning a second daemon at the same address.
                return await self.is_live()
            self._last_attempt = time.monotonic()
            try:
                await asyncio.to_thread(ensure_daemon, self._config, self._endpoint)
            except (DaemonError, OSError):
                logger.warning("Respawning the daemon failed", exc_info=True)
                return False
            return True


class DaemonRecoveryMiddleware(Middleware):
    """Turn "the daemon vanished" into one clear failure plus a working next call.

    Two ways in. A request that fails is first checked against the control channel:
    when the daemon still answers, the original error is genuine and is re-raised
    untouched. A request that neither fails nor returns is watched while it runs, and
    cancelled once the daemon is proven gone, which routes it into the same recovery.
    """

    def __init__(self, recovery: DaemonRecovery, client: StatefulProxyClient) -> None:
        self._recovery = recovery
        self._client = client
        # The daemon the cached backend session belongs to; None until first observed.
        self._bound: DaemonInstance | None = None

    async def on_message(
        self,
        context: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        if self._bound is None:
            self._bound = await self._recovery.instance()
        try:
            return await self._call_watched(context, call_next)
        except _DaemonVanishedError:
            raise await self._recover("it vanished holding an in-flight request") from None
        except Exception as exc:
            current = await self._recovery.instance()
            if current is None:
                raise await self._recover(f"the request failed with {type(exc).__name__}") from exc
            if self._bound is None or current == self._bound:
                raise
            raise await self._replaced(current) from exc

    async def _call_watched(
        self,
        context: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Run the request, giving up only once its daemon is proven to have died.

        The wait is driven by liveness, never by elapsed time: a healthy daemon can
        hold a call for minutes (a cold browser launch, a slow page) and nothing here
        will touch it. Every probe is between intervals, so a call that answers in
        milliseconds pays for none of them.
        """
        request = asyncio.ensure_future(call_next(context))
        confirmations = 0
        try:
            while confirmations < DEATH_CONFIRMATIONS:
                done, _ = await asyncio.wait({request}, timeout=WATCH_INTERVAL_S)
                if done:
                    return request.result()
                confirmations = confirmations + 1 if await self._recovery.is_gone() else 0
        except BaseException:
            # Includes the caller cancelling us: the request must not outlive it.
            await _abandon(request)
            raise
        await _abandon(request)
        raise _DaemonVanishedError

    async def _recover(self, reason: str) -> McpError:
        logger.warning("Daemon unreachable (%s); respawning", reason)
        if not await self._recovery.respawn():
            return _mcp_error(UNRECOVERED_MESSAGE)
        await self._drop_dead_backend()
        return _mcp_error(RESTARTED_MESSAGE)

    async def _replaced(self, current: DaemonInstance) -> McpError:
        """Another proxy already respawned the daemon: only the backend session is stale.

        Not retried, for the same reason a respawn is not: the failed request may have
        reached the old daemon before it went, and no request is ever sent twice.
        """
        logger.warning("Daemon %s was replaced by %s; reconnecting", self._bound, current)
        await self._drop_dead_backend()
        return _mcp_error(RESTARTED_MESSAGE)

    async def _drop_dead_backend(self) -> None:
        """Force-disconnect the cached backend session bound to the dead daemon.

        Without this the proxy keeps handing out a client whose MCP session id died
        with the old process, and the next call fails against the healthy daemon.
        """
        self._bound = None
        try:
            await self._client.clear()
        except Exception:
            logger.debug("Clearing the proxy backend cache failed", exc_info=True)


async def _abandon(request: asyncio.Future) -> None:
    """Cancel an outstanding request and wait for it to actually unwind.

    Returning before it has finished would leave its transport teardown racing the
    respawn that follows, so the outcome is awaited and then discarded: it is by
    construction either the cancellation itself or the failure of a dead connection.
    """
    request.cancel()
    try:
        await request
    except (Exception, asyncio.CancelledError):
        logger.debug("Abandoned in-flight request finished", exc_info=True)


def _mcp_error(message: str) -> McpError:
    return McpError(mcp.types.ErrorData(code=mcp.types.INTERNAL_ERROR, message=message))
