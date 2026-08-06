"""The Windows control channel: a loopback port, and the token guarding it."""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import socket
from typing import TYPE_CHECKING, Any

import httpx
from starlette.middleware import Middleware

from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.auth import TokenAuthMiddleware
from camoufox_mcp.daemon.endpoint import (
    DEFAULT_MCP_TIMEOUT,
    Bound,
    Conn,
    DaemonEndpoint,
    publish_advert,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig


class LoopbackEndpoint(DaemonEndpoint):
    """Windows control channel: a 127.0.0.1 TCP socket guarded by a bearer token.

    Windows cannot serve the daemon over a Unix socket (asyncio has no
    ``create_unix_server`` there), so the daemon binds an ephemeral loopback port
    and advertises ``{host, port, token}`` in a 0o600 ``daemon.endpoint`` file. The
    token, enforced by :class:`TokenAuthMiddleware`, replaces the socket file mode
    as the access boundary.
    """

    def resolve(self, config: ServerConfig) -> Conn | None:
        data = _read_endpoint_file(paths.endpoint_path(config))
        if data is None:
            return None
        return Conn(base_url=f"http://{data['host']}:{data['port']}", token=data["token"])

    def bind(self, config: ServerConfig) -> Bound:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        token = secrets.token_urlsafe(32)
        advert = {"host": "127.0.0.1", "port": port, "token": token}
        publish_advert(paths.endpoint_path(config), json.dumps(advert))
        return Bound(
            run_kwargs={"sockets": [sock]},
            middleware=[Middleware(TokenAuthMiddleware, token=token)],
            advert_id=self.advert_id(config),
            _socket=sock,
        )

    async def harden_when_ready(self, config: ServerConfig) -> None:
        """Nothing to restrict: the endpoint file is written 0o600 at :meth:`bind`."""

    def _cleanup(self, config: ServerConfig) -> None:
        with contextlib.suppress(OSError):
            paths.endpoint_path(config).unlink()

    def advert_id(self, config: ServerConfig) -> str | None:
        # Port plus a digest of the token: unique per daemon (the token is fresh on
        # every bind) without ever putting the secret itself in a log line.
        data = _read_endpoint_file(paths.endpoint_path(config))
        if data is None:
            return None
        digest = hashlib.sha256(str(data["token"]).encode("utf-8")).hexdigest()[:16]
        return f"{data['port']}:{digest}"

    def _sync_transport(self, conn: Conn) -> httpx.BaseTransport:
        return httpx.HTTPTransport()

    def mcp_client_factory(self, conn: Conn) -> Callable[..., httpx.AsyncClient]:
        headers = conn.auth_headers

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs.setdefault("timeout", DEFAULT_MCP_TIMEOUT)
            kwargs["headers"] = {**headers, **(kwargs.get("headers") or {})}
            return httpx.AsyncClient(**kwargs)

        return factory


def _read_endpoint_file(path: Path) -> dict[str, Any] | None:
    """The advert on disk, or ``None`` when there is nothing usable there.

    A corrupt advert is treated exactly like an unreadable one, and the type check is
    part of that: valid JSON that is not an object (``null``, ``3``, ``"x"``) answers
    ``key in data`` with a ``TypeError`` or, for a string, with a substring match, so
    without it both :meth:`LoopbackEndpoint.resolve` and
    :meth:`LoopbackEndpoint.advert_id` raise on a truncated or hand-edited file instead
    of reporting no daemon.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not all(key in data for key in ("host", "port", "token")):
        return None
    return data
