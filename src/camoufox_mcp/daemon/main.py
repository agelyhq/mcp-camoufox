from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from typing import TYPE_CHECKING

from camoufox_mcp.bootstrap import build_deps, build_server
from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon.endpoint import ENDPOINT
from camoufox_mcp.daemon.lifecycle import ActivityState, ActivityTracker, idle_watchdog
from camoufox_mcp.daemon.routes import register_daemon_routes

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the shared daemon: the REAL server over HTTP on the platform control channel.

    Invoked as ``python -m camoufox_mcp.daemon`` (or the ``camoufox-mcp-daemon``
    console script) by the thin stdio proxy. Auto-update, telemetry and the
    :class:`SessionManager` all live here, unchanged.
    """
    config = ServerConfig.from_env()
    _configure_logging()
    try:
        asyncio.run(_serve(config))
    finally:
        ENDPOINT.cleanup(config)


async def _serve(config: ServerConfig) -> None:
    config.ensure_daemon_dir()  # 0o700 parent must exist before the channel is bound
    bound = ENDPOINT.bind(config)
    deps = build_deps(config)
    mcp: FastMCP = build_server(config, deps=deps)
    state = ActivityState()
    register_daemon_routes(mcp, deps.sessions, state)
    mcp.add_middleware(ActivityTracker(state))

    watchdog = asyncio.create_task(idle_watchdog(config, deps.sessions, state))
    harden = asyncio.create_task(ENDPOINT.harden_when_ready(config))
    try:
        await mcp.run_http_async(
            transport="http",
            show_banner=False,
            host_origin_protection=False,
            middleware=bound.middleware,
            **bound.run_kwargs,
        )
    finally:
        for task in (watchdog, harden):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _configure_logging() -> None:
    # The parent detaches the daemon with stdout+stderr redirected to daemon.log,
    # so logging to stderr lands there and feeds DaemonSpawnError's tail.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


if __name__ == "__main__":
    main()
