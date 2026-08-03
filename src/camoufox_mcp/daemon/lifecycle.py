from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import TYPE_CHECKING, Any

from fastmcp.server.middleware import Middleware

from camoufox_mcp.telemetry import now_iso

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions import SessionManager

logger = logging.getLogger(__name__)

_MAX_CHECK_INTERVAL_S = 15.0
_MIN_CHECK_INTERVAL_S = 0.5


class ActivityState:
    """Mutable liveness state shared by the middleware, watchdog and /health route."""

    def __init__(self) -> None:
        self.started_at: str = now_iso()
        self.last_activity: float = time.monotonic()
        self.inflight: int = 0

    def touch(self) -> None:
        self.last_activity = time.monotonic()


class ActivityTracker(Middleware):
    """Stamp ``last_activity`` and track in-flight requests on every MCP message.

    Activity is stamped on entry AND exit, and the in-flight counter keeps the
    watchdog from firing mid-request: a long first call (cold browser launch)
    has ``active_count() == 0`` until the session lands, so idle time alone is
    not a safe termination signal.
    """

    def __init__(self, state: ActivityState) -> None:
        self._state = state

    async def on_message(
        self,
        context: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        self._state.touch()
        self._state.inflight += 1
        try:
            return await call_next(context)
        finally:
            self._state.inflight -= 1
            self._state.touch()


def schedule_self_terminate(delay: float = 0.1) -> None:
    """Ask uvicorn for a graceful shutdown by raising SIGTERM in this process.

    Deferred so an in-flight response (e.g. the /shutdown reply) flushes first.
    uvicorn installs a SIGTERM handler via ``signal.signal`` and its tick loop
    picks the signal up within ~0.1s. On Windows ``os.kill`` with a non-CTRL signal
    would call TerminateProcess — an abrupt kill that skips uvicorn's graceful
    shutdown and the daemon's endpoint cleanup — so the signal is raised in-process
    there instead.
    """
    loop = asyncio.get_running_loop()
    loop.call_later(delay, _raise_terminate)


def _raise_terminate() -> None:
    if sys.platform == "win32":
        signal.raise_signal(signal.SIGTERM)
    else:
        os.kill(os.getpid(), signal.SIGTERM)


async def idle_watchdog(
    config: ServerConfig,
    sessions: SessionManager,
    state: ActivityState,
) -> None:
    """Terminate the daemon once it has been idle (no sessions, no traffic) past TTL."""
    ttl = config.daemon_ttl_seconds
    interval = max(_MIN_CHECK_INTERVAL_S, min(_MAX_CHECK_INTERVAL_S, ttl / 4))
    while True:
        await asyncio.sleep(interval)
        idle_for = time.monotonic() - state.last_activity
        if sessions.active_count() == 0 and state.inflight == 0 and idle_for > ttl:
            logger.info("Daemon idle for %.0fs (ttl=%ss); shutting down", idle_for, ttl)
            schedule_self_terminate(0.0)
            return
