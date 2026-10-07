"""Bringing the daemon back when it dies in the middle of a conversation.

The daemon is ensured once, when a proxy starts. Without this module a daemon that
dies at call 12 takes calls 13 onward with it, each one failing on a bare
``Connection refused``. Here every request first renews this proxy's lease (see
:mod:`camoufox_mcp.daemon.lease`), which both proves a daemon is there and names the
process answering. When none is, it is respawned once and the caller gets the only
honest outcome: this call did not complete, the browser sessions the dead daemon held
are gone, and the next call will reach a fresh daemon.

The daemon serves stateless HTTP, so a daemon replaced behind this proxy's back (it
exited, another proxy spawned a new one) fails nothing: the next request would simply
land on a daemon that owns none of this conversation's browsers. The renewal is what
notices. A different pid or start time is reported exactly once, BEFORE the call is
forwarded, so "this call did not complete" is true; the following calls go through.
One race remains: a replacement landing between that check and the forwarded request
runs the call on the new daemon, and the NEXT call reports it. Late by one call, never
missed and never reported twice.

Only a request whose error reaches the model consumes that notice: a tool call, a
resource read, a prompt get. A list request (``tools/list``, ``resources/list``...) is
issued by the client on its own and its error is never shown, so it is repaired
silently and leaves the notice for the next call that can deliver it. The opening
``initialize`` clears it instead: a conversation that has not started has no browser
to lose. A request already in flight is a different matter: it remembers the daemon
instance it was sent to, and fails with the restart message whenever that instance is
gone, however many other requests have already reported the same restart.

A daemon that dies mid-request raises nothing at all. The streamable-HTTP response is
never written, the connection stays open from the client's side, and the transport read
timeout is far longer than any conversation can wait: measured, the call was still
pending 180 s after the kill. So an outstanding request is also watched from the
outside, by renewing the lease on a timer and cancelling the call once its daemon is
proven gone or proven replaced.

The respawn is deliberately NOT a replay of the failed request. A replay would either
re-run an action the dying daemon may already have performed, or land on a daemon that
owns no browser and fail again for a second reason. The TTL accounting stays exact for
the same reason: the daemon counts in-flight requests, and no request is ever sent twice.
A cancellation cannot strand that counter either, since the only request ever cancelled
here is one whose daemon no longer exists.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import mcp.types
from fastmcp.server.middleware import Middleware
from mcp.shared.exceptions import McpError

from camoufox_mcp.daemon.errors import DaemonError
from camoufox_mcp.daemon.lease_client import Alive, Gone
from camoufox_mcp.daemon.spawn import ensure_daemon

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp.server.providers.proxy import StatefulProxyClient

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.daemon.endpoint import DaemonEndpoint
    from camoufox_mcp.daemon.identity import DaemonInstance
    from camoufox_mcp.daemon.lease import DaemonLease

logger = logging.getLogger(__name__)

# Long enough that a burst of concurrent failures shares one respawn, short enough
# that a second, genuinely later crash is still repaired.
_RESPAWN_COOLDOWN_S = 5.0

# How often an outstanding request checks that its daemon still exists, and how many
# consecutive checks must agree before the call is cancelled. Two, not one, because a
# Unix socket whose accept backlog is momentarily full also refuses connections; that
# clears in milliseconds, so a second refusal a whole interval later is real. A changed
# daemon instance needs no second opinion: it is positive proof on its own.
WATCH_INTERVAL_S = 2.0
DEATH_CONFIRMATIONS = 2

_OPENING_METHOD = "initialize"
# The requests whose failure the model reads, so the only ones that can deliver a notice.
_REPORTING_METHODS = frozenset({"tools/call", "resources/read", "prompts/get"})


class _DaemonVanishedError(Exception):
    """The daemon holding this request disappeared while it was outstanding."""


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

    def __init__(self, config: ServerConfig, endpoint: DaemonEndpoint, lease: DaemonLease) -> None:
        self._config = config
        self._endpoint = endpoint
        self._lease = lease
        self._lock = asyncio.Lock()
        # -inf, not 0.0: time.monotonic() counts from boot, so a proxy started
        # seconds after boot would otherwise see its first respawn as a duplicate.
        self._last_attempt = float("-inf")

    async def respawn(self) -> bool:
        """Ensure a daemon is listening again, at most once per cooldown window."""
        async with self._lock:
            if time.monotonic() - self._last_attempt < _RESPAWN_COOLDOWN_S:
                # A concurrent failure just respawned; report that one's outcome
                # instead of spawning a second daemon at the same address.
                return isinstance(await self._lease.check(), Alive)
            self._last_attempt = time.monotonic()
            try:
                await asyncio.to_thread(ensure_daemon, self._config, self._endpoint)
            except (DaemonError, OSError):
                logger.warning("Respawning the daemon failed", exc_info=True)
                return False
            return True


class DaemonRecoveryMiddleware(Middleware):
    """Turn "the daemon vanished" into one clear failure plus a working next call.

    Three ways in. Every request renews the lease before it is forwarded: no daemon
    means respawn, a different daemon means report the replacement. A request that
    fails is checked again the same way, and the original error is re-raised untouched
    when the daemon it went to is still there. A request that neither fails nor returns
    is watched while it runs, and cancelled once its daemon is proven gone or replaced.
    """

    def __init__(
        self, recovery: DaemonRecovery, client: StatefulProxyClient, lease: DaemonLease
    ) -> None:
        self._recovery = recovery
        self._client = client
        self._lease = lease

    async def on_message(
        self,
        context: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        method = getattr(context, "method", None)
        reports = method in _REPORTING_METHODS
        if context.type == "request":
            await self._precheck(opening=method == _OPENING_METHOD, reports=reports)
        sent_to = self._lease.bound
        try:
            return await self._call_watched(context, call_next, sent_to)
        except _DaemonVanishedError:
            if self._moved(sent_to):
                raise await self._replaced(reports, drop=True) from None
            raise await self._recover(reports, "it vanished holding a request") from None
        except Exception as exc:
            probe = await self._lease.check()
            if isinstance(probe, Gone):
                reason = f"the request failed with {type(exc).__name__}"
                raise await self._recover(reports, reason) from exc
            if self._moved(sent_to):
                raise await self._replaced(reports, drop=True) from exc
            raise

    async def _precheck(self, *, opening: bool, reports: bool) -> None:
        """Stop a request before it reaches a missing or replaced daemon.

        Only a request that ``reports`` fails here. Any other is repaired silently and,
        unless it is the opening handshake (no conversation, so no browser to lose),
        leaves the restart pending for the next request that can report it.
        """
        probe = await self._lease.check()
        if isinstance(probe, Gone):
            if reports:
                raise await self._recover(reports, "no daemon answers")
            if not await self._recovery.respawn():
                raise _mcp_error(UNRECOVERED_MESSAGE)
            await self._lease.adopt_current()
            await self._drop_dead_backend()
            if not opening:
                self._lease.raise_notice()
            return
        if opening:
            self._lease.take_notice()
        elif reports and self._lease.take_notice():
            # Nothing failed on the cached backend: stateless requests simply reach the
            # new daemon, so there is no stale client to drop.
            raise await self._replaced(reports, drop=False)

    async def _call_watched(
        self,
        context: Any,
        call_next: Callable[[Any], Awaitable[Any]],
        sent_to: DaemonInstance | None,
    ) -> Any:
        """Run the request, giving up only once its daemon is proven gone or replaced.

        The wait is driven by liveness, never by elapsed time: a healthy daemon can
        hold a call for minutes (a cold browser launch, a slow page) and nothing here
        will touch it. Every probe is between intervals, so a call that answers in
        milliseconds pays for none of them. Replacement is judged against ``sent_to``,
        the instance this very request went to, never against a shared flag another
        request may already have consumed.
        """
        request = asyncio.ensure_future(call_next(context))
        confirmations = 0
        try:
            while confirmations < DEATH_CONFIRMATIONS and not self._moved(sent_to):
                done, _ = await asyncio.wait({request}, timeout=WATCH_INTERVAL_S)
                if done:
                    return request.result()
                probe = await self._lease.check()
                confirmations = confirmations + 1 if isinstance(probe, Gone) else 0
        except BaseException:
            # Includes the caller cancelling us: the request must not outlive it.
            await _abandon(request)
            raise
        await _abandon(request)
        raise _DaemonVanishedError

    def _moved(self, sent_to: DaemonInstance | None) -> bool:
        """True once the daemon a request went to is no longer the one bound.

        An unbound lease (a respawn whose first renewal proved nothing) is no verdict:
        the next ``Alive`` binds it, and only then does a different instance count.
        """
        bound = self._lease.bound
        return sent_to is not None and bound is not None and bound != sent_to

    async def _recover(self, reports: bool, reason: str) -> McpError:
        logger.warning("Daemon unreachable (%s); respawning", reason)
        if not await self._recovery.respawn():
            return _mcp_error(UNRECOVERED_MESSAGE)
        await self._lease.adopt_current()
        await self._drop_dead_backend()
        if not reports:
            self._lease.raise_notice()
        return _mcp_error(RESTARTED_MESSAGE)

    async def _replaced(self, reports: bool, *, drop: bool) -> McpError:
        """Another proxy already respawned the daemon: report it, do not respawn again.

        Not retried, for the same reason a respawn is not: the request may have reached
        the old daemon before it went, and no request is ever sent twice. A reporting
        request delivers the pending notice; any other leaves it for one that can.
        """
        if reports:
            self._lease.take_notice()
        if drop:
            await self._drop_dead_backend()
        return _mcp_error(RESTARTED_MESSAGE)

    async def _drop_dead_backend(self) -> None:
        """Force-disconnect the cached backend client after a failure broke it.

        A client whose connection failed mid-request stays unusable even once a daemon
        answers again, so the next call must build a fresh one.
        """
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
