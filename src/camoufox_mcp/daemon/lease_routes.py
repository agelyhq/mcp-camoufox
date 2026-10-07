"""The ``/lease`` control routes: how a proxy tells the daemon it is still connected.

Same channel, same guard as ``/health`` and ``/shutdown``: a 0o600 Unix socket on POSIX,
and on Windows the per-daemon bearer token that ``TokenAuthMiddleware`` checks on every
route, so nothing here authenticates on its own. A renewal deliberately does not count
as activity: the idle TTL is measured from the moment the last lease goes (see
:meth:`LeaseTable.vacated_at`), and a heartbeat stamping ``last_activity`` would only
blur that.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from camoufox_mcp.daemon.errors import LeaseClosedError, LeaseLimitError

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from starlette.requests import Request

    from camoufox_mcp.daemon.identity import DaemonInstance
    from camoufox_mcp.daemon.leases import LeaseTable

# What a proxy draws from secrets.token_hex(16). Anything else is refused rather than
# stored, so the table never holds an arbitrary client-chosen string.
_LEASE_ID = re.compile(r"[0-9a-f]{32}")
# What a daemon that has decided to exit answers a grant with, ``{"closing": true}`` in
# the body: the proxy reads it as "gone", exactly as if the daemon had already exited.
CLOSING_STATUS = 503


def register_lease_routes(mcp: FastMCP, table: LeaseTable, instance: DaemonInstance) -> None:
    """Attach ``POST /lease`` (grant or renew) and ``DELETE /lease/{id}`` to ``mcp``.

    The grant answers with this daemon's :class:`DaemonInstance`, so every renewal is
    also the proxy's proof of which process it is talking to.
    """

    @mcp.custom_route("/lease", methods=["POST"])
    async def grant(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            return _bad_request("the body is not JSON")
        parsed = _parse_grant(body)
        if isinstance(parsed, str):
            return _bad_request(parsed)
        lease_id, ttl_s = parsed
        try:
            granted = table.grant(lease_id, ttl_s)
        except LeaseClosedError as exc:
            return JSONResponse({"error": str(exc), "closing": True}, status_code=CLOSING_STATUS)
        except LeaseLimitError as exc:
            return JSONResponse({"error": str(exc)}, status_code=429)
        return JSONResponse({**instance.as_payload(), "ttl_s": granted})

    @mcp.custom_route("/lease/{lease_id}", methods=["DELETE"])
    async def release(request: Request) -> JSONResponse:
        lease_id = request.path_params["lease_id"]
        if not _LEASE_ID.fullmatch(lease_id):
            return _bad_request("the lease id is not 32 lowercase hex digits")
        return JSONResponse({"released": table.release(lease_id)})


def _parse_grant(body: object) -> tuple[str, float] | str:
    """``(lease_id, ttl_s)`` from a grant body, or the reason it is unusable."""
    if not isinstance(body, dict):
        return "the body is not a JSON object"
    lease_id = body.get("id")
    if not isinstance(lease_id, str) or not _LEASE_ID.fullmatch(lease_id):
        return "'id' is not 32 lowercase hex digits"
    ttl_s = body.get("ttl_s")
    if isinstance(ttl_s, bool) or not isinstance(ttl_s, int | float):
        return "'ttl_s' is not a number"
    if not math.isfinite(ttl_s) or ttl_s <= 0:
        return "'ttl_s' must be a finite number of seconds above 0"
    return lease_id, float(ttl_s)


def _bad_request(reason: str) -> JSONResponse:
    return JSONResponse({"error": reason}, status_code=400)
