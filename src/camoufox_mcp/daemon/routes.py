from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from camoufox_mcp.daemon.lifecycle import schedule_self_terminate

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from starlette.requests import Request

    from camoufox_mcp.daemon.identity import DaemonIdentity, DaemonInstance
    from camoufox_mcp.daemon.leases import LeaseTable
    from camoufox_mcp.sessions import SessionManager


def register_daemon_routes(
    mcp: FastMCP,
    identity: DaemonIdentity,
    instance: DaemonInstance,
    sessions: SessionManager,
    leases: LeaseTable,
) -> None:
    """Attach the /health and /shutdown control routes to ``mcp``.

    Both are plain Starlette routes outside the MCP protocol, reachable only over the
    daemon's control channel: a 0o600 Unix socket on POSIX, and on Windows a loopback
    port that ``TokenAuthMiddleware`` gates on the per-daemon bearer token. Neither
    platform ever exposes them on a routable interface.
    """

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                **identity.as_health(),
                **instance.as_payload(),
                "active_sessions": sessions.active_count(),
                "leases": leases.live_count(),
                "closing": leases.closed,
            }
        )

    @mcp.custom_route("/shutdown", methods=["POST"])
    async def shutdown(request: Request) -> JSONResponse:
        # A live lease is a connected proxy: shutting its daemon down unforced would
        # report a restart to a conversation where nothing died.
        force = request.query_params.get("force") == "true"
        active, leased = sessions.active_count(), leases.live_count()
        if (active > 0 or leased > 0) and not force:
            return JSONResponse(
                {"status": "refused", "active_sessions": active, "leases": leased},
                status_code=409,
            )
        leases.close()
        schedule_self_terminate()
        return JSONResponse({"status": "shutting_down"})
