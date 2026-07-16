from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from typing import TYPE_CHECKING

from camoufox_mcp.bootstrap import build_deps, build_server
from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon.lifecycle import ActivityState, ActivityTracker, idle_watchdog
from camoufox_mcp.daemon.routes import register_daemon_routes

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the shared daemon: the REAL server over HTTP on a Unix domain socket.

    Invoked as ``python -m camoufox_mcp.daemon`` (or the ``camoufox-mcp-daemon``
    console script) by the thin stdio proxy. Auto-update, telemetry and the
    :class:`SessionManager` all live here, unchanged.
    """
    config = ServerConfig.from_env()
    _configure_logging()
    try:
        asyncio.run(_serve(config))
    finally:
        _cleanup_socket(config)


async def _serve(config: ServerConfig) -> None:
    config.ensure_daemon_dir()  # 0o700 parent must exist before uvicorn binds the UDS
    deps = build_deps(config)
    mcp: FastMCP = build_server(config, deps=deps)
    state = ActivityState()
    register_daemon_routes(mcp, deps.sessions, state)
    mcp.add_middleware(ActivityTracker(state))

    watchdog = asyncio.create_task(idle_watchdog(config, deps.sessions, state))
    tighten = asyncio.create_task(_tighten_socket_mode(config.daemon_socket_path))
    try:
        await mcp.run_http_async(
            transport="http",
            show_banner=False,
            host_origin_protection=False,
            uvicorn_config={"uds": str(config.daemon_socket_path)},
        )
    finally:
        for task in (watchdog, tighten):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _tighten_socket_mode(socket_path: Path) -> None:
    """Restrict the control socket to the owning user as soon as uvicorn binds it.

    uvicorn chmods a freshly created Unix socket to 0o666; that would let any
    local user reach /shutdown and the full browser-driving MCP surface.
    """
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if socket_path.exists():
            socket_path.chmod(0o600)
            return
        await asyncio.sleep(0.05)


def _cleanup_socket(config: ServerConfig) -> None:
    with contextlib.suppress(OSError):
        config.daemon_socket_path.unlink()


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
