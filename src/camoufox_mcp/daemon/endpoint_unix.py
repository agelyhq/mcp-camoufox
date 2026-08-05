"""The POSIX control channel: a Unix domain socket, and the advert naming it."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

import httpx

from camoufox_mcp.daemon.endpoint import DEFAULT_MCP_TIMEOUT, Bound, Conn, DaemonEndpoint
from camoufox_mcp.daemon.socket_path import (
    address_pointer_path,
    check_socket_path,
    daemon_socket_path,
    ensure_socket_dir,
    publish_socket_path,
    published_socket_path,
    unpublish_socket_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from camoufox_mcp.config import ServerConfig

_UDS_HOST = "http://camoufox-daemon"
_HARDEN_DEADLINE_S = 10.0
_HARDEN_POLL_S = 0.05


class UnixSocketEndpoint(DaemonEndpoint):
    """POSIX control channel: a 0o600 Unix domain socket in a 0o700 directory.

    The socket lives under ``XDG_RUNTIME_DIR`` when there is one, because
    ``sun_path`` is far too short to hold an arbitrary data dir. Binding therefore
    uses the address derived here and now, while resolving follows the pointer the
    running daemon left in the data dir (see :mod:`camoufox_mcp.daemon.socket_path`).
    """

    def resolve(self, config: ServerConfig) -> Conn | None:
        path = published_socket_path(config)
        if not path.exists():
            return None
        return Conn(base_url=_UDS_HOST, socket_path=str(path))

    def bind(self, config: ServerConfig) -> Bound:
        path = daemon_socket_path(config)
        check_socket_path(path)
        ensure_socket_dir(config)
        publish_socket_path(config, path)
        return Bound(
            run_kwargs={"uvicorn_config": {"uds": str(path)}},
            advert_id=self.advert_id(config),
        )

    async def harden_when_ready(self, config: ServerConfig) -> None:
        # uvicorn chmods a freshly created Unix socket to 0o666; that would let any
        # local user reach /shutdown and the full browser-driving MCP surface.
        path = daemon_socket_path(config)
        deadline = time.monotonic() + _HARDEN_DEADLINE_S
        while time.monotonic() < deadline:
            if path.exists():
                path.chmod(0o600)
                return
            await asyncio.sleep(_HARDEN_POLL_S)

    def _cleanup(self, config: ServerConfig) -> None:
        with contextlib.suppress(OSError):
            published_socket_path(config).unlink()
        unpublish_socket_path(config)

    def advert_id(self, config: ServerConfig) -> str | None:
        # The pointer first: the daemon writes it itself, atomically and long before
        # uvicorn creates the socket, so every publication has a distinct inode and a
        # daemon holds its own proof from bind() onwards. A socket with no pointer is
        # the advert a crashed daemon left, and naming it is what lets the next spawn
        # reclaim the address rather than refuse it.
        for path in (address_pointer_path(config), published_socket_path(config)):
            try:
                stat = path.stat()
            except OSError:
                continue
            return f"{stat.st_dev}:{stat.st_ino}"
        return None

    def _sync_transport(self, conn: Conn) -> httpx.BaseTransport:
        return httpx.HTTPTransport(uds=conn.socket_path)

    def mcp_client_factory(self, conn: Conn) -> Callable[..., httpx.AsyncClient]:
        socket_path = conn.socket_path

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs.setdefault("timeout", DEFAULT_MCP_TIMEOUT)
            return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket_path), **kwargs)

        return factory
