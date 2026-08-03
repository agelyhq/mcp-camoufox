from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import socket
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from starlette.middleware import Middleware

from camoufox_mcp.daemon.auth import TokenAuthMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from camoufox_mcp.config import ServerConfig

IS_WINDOWS = os.name == "nt"

_UDS_HOST = "http://camoufox-daemon"
_MCP_PATH = "/mcp"
_DEFAULT_MCP_TIMEOUT = httpx.Timeout(30.0, read=300.0)
_HARDEN_DEADLINE_S = 10.0
_HARDEN_POLL_S = 0.05


@dataclass(frozen=True)
class Conn:
    """A resolved address for reaching a running daemon's control HTTP server."""

    base_url: str
    socket_path: str | None = None
    token: str | None = None

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}


@dataclass
class Bound:
    """What the daemon must feed ``run_http_async`` to serve, plus its control token.

    ``run_kwargs`` are spread into ``run_http_async`` (a ``uvicorn_config`` with a
    ``uds`` on POSIX, a pre-bound ``sockets`` list on Windows). ``_socket`` is held
    only to keep the pre-bound socket alive until uvicorn adopts it.
    """

    run_kwargs: dict[str, Any]
    middleware: list[Middleware] = field(default_factory=list)
    token: str | None = None
    _socket: socket.socket | None = None


class DaemonEndpoint(ABC):
    """Platform strategy for the daemon's control channel (transport + lifecycle)."""

    @abstractmethod
    def resolve(self, config: ServerConfig) -> Conn | None:
        """Connection details for a published daemon, or ``None`` if none is advertised."""

    @abstractmethod
    def bind(self, config: ServerConfig) -> Bound:
        """Reserve the listen address (and, on Windows, a token) before uvicorn starts."""

    @abstractmethod
    async def harden_when_ready(self, config: ServerConfig) -> None:
        """Restrict the freshly bound control channel to its owner."""

    @abstractmethod
    def cleanup(self, config: ServerConfig) -> None:
        """Remove any on-disk address advert left by this daemon."""

    @abstractmethod
    def _sync_transport(self, conn: Conn) -> httpx.BaseTransport: ...

    @abstractmethod
    def mcp_client_factory(self, conn: Conn) -> Callable[..., httpx.AsyncClient]:
        """Async-client factory for the proxy's ``StreamableHttpTransport``."""

    def sync_client(self, conn: Conn, timeout: float = 2.0) -> httpx.Client:
        return httpx.Client(
            transport=self._sync_transport(conn),
            base_url=conn.base_url,
            headers=conn.auth_headers,
            timeout=timeout,
        )

    def mcp_url(self, conn: Conn) -> str:
        return f"{conn.base_url}{_MCP_PATH}"


class UnixSocketEndpoint(DaemonEndpoint):
    """POSIX control channel: a 0o600 Unix domain socket under the 0o700 daemon dir."""

    def resolve(self, config: ServerConfig) -> Conn | None:
        if not config.daemon_socket_path.exists():
            return None
        return Conn(base_url=_UDS_HOST, socket_path=str(config.daemon_socket_path))

    def bind(self, config: ServerConfig) -> Bound:
        return Bound(run_kwargs={"uvicorn_config": {"uds": str(config.daemon_socket_path)}})

    async def harden_when_ready(self, config: ServerConfig) -> None:
        # uvicorn chmods a freshly created Unix socket to 0o666; that would let any
        # local user reach /shutdown and the full browser-driving MCP surface.
        deadline = time.monotonic() + _HARDEN_DEADLINE_S
        while time.monotonic() < deadline:
            if config.daemon_socket_path.exists():
                config.daemon_socket_path.chmod(0o600)
                return
            await asyncio.sleep(_HARDEN_POLL_S)

    def cleanup(self, config: ServerConfig) -> None:
        with contextlib.suppress(OSError):
            config.daemon_socket_path.unlink()

    def _sync_transport(self, conn: Conn) -> httpx.BaseTransport:
        return httpx.HTTPTransport(uds=conn.socket_path)

    def mcp_client_factory(self, conn: Conn) -> Callable[..., httpx.AsyncClient]:
        socket_path = conn.socket_path

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs.setdefault("timeout", _DEFAULT_MCP_TIMEOUT)
            return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket_path), **kwargs)

        return factory


class LoopbackEndpoint(DaemonEndpoint):
    """Windows control channel: a 127.0.0.1 TCP socket guarded by a bearer token.

    Windows cannot serve the daemon over a Unix socket (asyncio has no
    ``create_unix_server`` there), so the daemon binds an ephemeral loopback port
    and advertises ``{host, port, token}`` in a 0o600 ``daemon.endpoint`` file. The
    token, enforced by :class:`TokenAuthMiddleware`, replaces the socket file mode
    as the access boundary.
    """

    def resolve(self, config: ServerConfig) -> Conn | None:
        data = _read_endpoint_file(config.daemon_endpoint_path)
        if data is None:
            return None
        return Conn(base_url=f"http://{data['host']}:{data['port']}", token=data["token"])

    def bind(self, config: ServerConfig) -> Bound:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        token = secrets.token_urlsafe(32)
        _write_endpoint_file(
            config.daemon_endpoint_path, {"host": "127.0.0.1", "port": port, "token": token}
        )
        return Bound(
            run_kwargs={"sockets": [sock]},
            middleware=[Middleware(TokenAuthMiddleware, token=token)],
            token=token,
            _socket=sock,
        )

    async def harden_when_ready(self, config: ServerConfig) -> None:
        # The endpoint file is written 0o600 at bind(); nothing else to restrict.
        return

    def cleanup(self, config: ServerConfig) -> None:
        with contextlib.suppress(OSError):
            config.daemon_endpoint_path.unlink()

    def _sync_transport(self, conn: Conn) -> httpx.BaseTransport:
        return httpx.HTTPTransport()

    def mcp_client_factory(self, conn: Conn) -> Callable[..., httpx.AsyncClient]:
        headers = conn.auth_headers

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs.setdefault("timeout", _DEFAULT_MCP_TIMEOUT)
            kwargs["headers"] = {**headers, **(kwargs.get("headers") or {})}
            return httpx.AsyncClient(**kwargs)

        return factory


def _read_endpoint_file(path: Any) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not all(key in data for key in ("host", "port", "token")):
        return None
    return data


def _write_endpoint_file(path: Any, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    os.replace(tmp, path)


ENDPOINT: DaemonEndpoint = LoopbackEndpoint() if IS_WINDOWS else UnixSocketEndpoint()
