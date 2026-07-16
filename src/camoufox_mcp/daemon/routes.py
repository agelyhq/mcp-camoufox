from __future__ import annotations

import os
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from camoufox_mcp.daemon.identity import code_path, pkg_version
from camoufox_mcp.daemon.lifecycle import schedule_self_terminate

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from starlette.requests import Request

    from camoufox_mcp.daemon.lifecycle import ActivityState
    from camoufox_mcp.sessions import SessionManager


def register_daemon_routes(
    mcp: FastMCP,
    sessions: SessionManager,
    state: ActivityState,
) -> None:
    """Attach the UDS-only /health and /shutdown control routes to ``mcp``.

    Both are plain Starlette routes outside the MCP protocol; they are reachable only
    over the daemon's Unix domain socket, never a network interface.
    """

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "version": pkg_version(),
                "code_path": code_path(),
                "active_sessions": sessions.active_count(),
                "started_at": state.started_at,
                "pid": os.getpid(),
            }
        )

    @mcp.custom_route("/shutdown", methods=["POST"])
    async def shutdown(request: Request) -> JSONResponse:
        force = request.query_params.get("force") == "true"
        active = sessions.active_count()
        if active > 0 and not force:
            return JSONResponse(
                {"status": "refused", "active_sessions": active},
                status_code=409,
            )
        schedule_self_terminate()
        return JSONResponse({"status": "shutting_down"})
