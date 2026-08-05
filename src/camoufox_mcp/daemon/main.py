from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from functools import partial
from typing import TYPE_CHECKING

from camoufox_mcp.bootstrap import build_deps, build_server
from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.endpoint import select_endpoint
from camoufox_mcp.daemon.identity import local_identity
from camoufox_mcp.daemon.lifecycle import (
    ActivityState,
    ActivityTracker,
    cleanup_on_termination,
    idle_watchdog,
)
from camoufox_mcp.daemon.routes import register_daemon_routes

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.daemon.endpoint import DaemonEndpoint

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the shared daemon: the REAL server over HTTP on the platform control channel.

    Invoked as ``python -m camoufox_mcp.daemon`` (or the ``mcp-camoufox-daemon``
    console script) by the thin stdio proxy. Auto-update, telemetry and the
    :class:`SessionManager` all live here, unchanged.
    """
    config = ServerConfig.from_env()
    _configure_logging()
    asyncio.run(_serve(config))


async def _serve(config: ServerConfig) -> None:
    # The daemon's composition root: one control-channel strategy, passed to the two
    # places that use it (the bind below and the advert release on the way out).
    endpoint = select_endpoint()
    paths.ensure_daemon_dir(config)  # 0o700 parent must exist before the channel is bound
    bound = endpoint.bind(config)
    release = partial(_release_advert, config, endpoint, bound.advert_id)
    # Registered before anything below can fail, so the advert is withdrawn on every
    # signal exit from its publication onwards. A signal exit reaches nothing written
    # after run_http_async, finally blocks included: see lifecycle.cleanup_on_termination.
    with cleanup_on_termination(release):
        deps = build_deps(config)
        mcp: FastMCP = build_server(config, deps=deps)
        state = ActivityState()
        register_daemon_routes(mcp, local_identity(config), deps.sessions, state)
        mcp.add_middleware(ActivityTracker(state))

        watchdog = asyncio.create_task(idle_watchdog(config, deps.sessions, state))
        harden = asyncio.create_task(endpoint.harden_when_ready(config))
        try:
            await mcp.run_http_async(
                transport="http",
                show_banner=False,
                host_origin_protection=False,
                middleware=bound.middleware,
                **bound.run_kwargs,
            )
            # Reached only when uvicorn stopped without a signal, so nothing else is
            # going to withdraw the advert. A raise skips this on purpose: an OSError
            # here is the address already belonging to another daemon, which must keep
            # what is published, and the next proxy clears a leftover safely.
            release()
        finally:
            for task in (watchdog, harden):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def _release_advert(config: ServerConfig, endpoint: DaemonEndpoint, advert_id: str | None) -> None:
    """Withdraw the address advert, but only the one this daemon published.

    ``advert_id`` is what :meth:`DaemonEndpoint.bind` read back the moment it published,
    this process's proof of ownership. Without a match nothing is unlinked: an advert on
    disk may belong to a daemon that is still serving, and removing it would leave its
    browsers running with no way to reach them.
    """
    if advert_id is None:
        return
    endpoint.cleanup_if_owned(config, advert_id)


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
