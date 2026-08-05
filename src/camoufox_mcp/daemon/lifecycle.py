from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
from typing import TYPE_CHECKING, Any

from fastmcp.server.middleware import Middleware

from camoufox_mcp.telemetry import now_iso

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from types import FrameType

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions import SessionManager

logger = logging.getLogger(__name__)

_MAX_CHECK_INTERVAL_S = 15.0
_MIN_CHECK_INTERVAL_S = 0.5

# The same set uvicorn captures, so whatever it hands back is handled here too.
_TERMINATION_SIGNALS = tuple(
    getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, name)
)


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
    would call TerminateProcess, an abrupt kill that skips uvicorn's graceful
    shutdown and the daemon's endpoint cleanup, so the signal is raised in-process
    there instead.
    """
    loop = asyncio.get_running_loop()
    loop.call_later(delay, _raise_terminate)


def _raise_terminate() -> None:
    if sys.platform == "win32":
        signal.raise_signal(signal.SIGTERM)
    else:
        os.kill(os.getpid(), signal.SIGTERM)


@contextlib.contextmanager
def cleanup_on_termination(cleanup: Callable[[], None]) -> Iterator[None]:
    """Run ``cleanup`` when a signal ends this process, before the process dies.

    Nothing written after ``run_http_async`` runs on a signal exit, ``finally`` blocks
    included: uvicorn captures SIGTERM, shuts down gracefully, restores the handler that
    was installed before it, then re-raises the signal it caught. With the default
    handler back in place that call is where the daemon dies. Since a signal is the ONLY
    way this daemon ever exits (the idle watchdog and /shutdown both raise SIGTERM), the
    advert was left on disk by every clean exit. Python 3.13's asyncio unlinks a closed
    Unix socket by itself and 3.12 does not, which is why that only ever showed on the
    3.12 release runner.

    The handler installed here is the one uvicorn restores, so it runs at exactly that
    point, with the server already stopped. It then re-raises under the default handler,
    so terminating still means terminating.
    """

    def handler(signum: int, _frame: FrameType | None) -> None:
        cleanup()
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)

    previous = {sig: signal.signal(sig, handler) for sig in _TERMINATION_SIGNALS}
    try:
        yield
    finally:
        for sig, handler_before in previous.items():
            signal.signal(sig, handler_before)


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
