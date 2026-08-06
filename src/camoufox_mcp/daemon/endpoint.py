"""The daemon's control channel, as an abstraction plus the factory that picks one.

Each platform serves the daemon's private HTTP on a different kind of address, and the
2 strategies live in :mod:`camoufox_mcp.daemon.endpoint_unix` and
:mod:`camoufox_mcp.daemon.endpoint_loopback`. Everything else in the daemon depends on
the abstraction here and receives a strategy as an argument.

The 1 write both strategies make, :func:`publish_advert`, lives here rather than in
either of them: what it does to a control channel's address on disk is a security
property, and 2 copies of a security property drift.
"""

from __future__ import annotations

import contextlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable
    from pathlib import Path

    from starlette.middleware import Middleware

    from camoufox_mcp.config import ServerConfig

IS_WINDOWS = os.name == "nt"

_MCP_PATH = "/mcp"
DEFAULT_MCP_TIMEOUT = httpx.Timeout(30.0, read=300.0)


def publish_advert(path: Path, text: str) -> None:
    """Write an advert naming a running daemon's address: atomically, owner-only.

    The 1 write both strategies make. The POSIX address pointer and the Windows endpoint
    file are the same kind of object, a control channel's address on disk, and 0o600 on it
    is a security property rather than tidiness, so it is set in 1 place instead of 2 that
    can drift apart.

    Both halves of the sequence are load-bearing. The temporary file plus
    :func:`os.replace` means a reader never sees a half-written address, and it also makes
    every publication land as a DISTINCT inode: that inode is the proof a daemon takes at
    ``bind`` that the advert it withdraws on the way out is still its own and not one a
    later daemon wrote at the same address. Unlinking another daemon's advert leaves it
    running with no control channel and its browsers unreachable. The mode is set before
    the rename, so the file is never reachable at a wider one, and a platform that refuses
    the ``chmod`` (Windows, where the bearer token is the real boundary) still publishes.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    os.replace(tmp, path)


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
    """What the daemon must feed ``run_http_async`` to serve, and what it proved binding.

    ``run_kwargs`` are spread into ``run_http_async`` (a ``uvicorn_config`` with a
    ``uds`` on POSIX, a pre-bound ``sockets`` list on Windows). ``_socket`` is held
    only to keep the pre-bound socket alive until uvicorn adopts it. A control token,
    where the platform needs one, travels in ``middleware`` and nowhere else: the daemon
    enforces it, never reads it.

    ``advert_id`` is the identity of the advert this bind published, read back the
    instant it was written: the daemon's proof, in hand before it serves a single
    request, that the advert it withdraws on the way out is still its own.
    """

    run_kwargs: dict[str, Any]
    middleware: list[Middleware] = field(default_factory=list)
    advert_id: str | None = None
    _socket: socket.socket | None = None


class DaemonEndpoint(ABC):
    """Platform strategy for the daemon's control channel (transport + lifecycle)."""

    @abstractmethod
    def resolve(self, config: ServerConfig) -> Conn | None:
        """Connection details for a published daemon, or ``None`` if none is advertised."""

    @abstractmethod
    def bind(self, config: ServerConfig) -> Bound:
        """Reserve the listen address (and, on Windows, a token) before uvicorn starts.

        Publishing the advert and reading its identity back happen here, in one
        synchronous step, so the returned :attr:`Bound.advert_id` is available on
        every exit path this daemon has, including the ones a signal cuts short.
        """

    @abstractmethod
    async def harden_when_ready(self, config: ServerConfig) -> None:
        """Restrict the freshly bound control channel to its owner.

        Its single job. Ownership is proved at :meth:`bind`, never here: a background
        task can be cancelled before it produces anything, and an advert whose owner
        never obtained its proof can no longer be withdrawn by anyone.
        """

    @abstractmethod
    def _cleanup(self, config: ServerConfig) -> None:
        """Unlink the on-disk address advert unconditionally.

        Private on purpose: every caller goes through :meth:`cleanup_if_owned`, so
        no code path can remove an advert without first proving whose it is.
        """

    @abstractmethod
    def advert_id(self, config: ServerConfig) -> str | None:
        """Identity of the advert published right now, or ``None`` when there is none.

        It changes as soon as a different daemon publishes at the same address, so a
        caller can tell the advert it inspected from one written since.
        """

    def cleanup_if_owned(self, config: ServerConfig, advert_id: str) -> bool:
        """Remove the advert unless it now belongs to a different daemon.

        Unlinking whatever happens to be published is how a live daemon loses its only
        control channel: its browsers keep running, unreachable. So the advert goes
        only when it is still the one identified by ``advert_id``, or already gone (a
        daemon whose socket the server removed on its way out still has a pointer to
        withdraw). Callers pair this with a health probe, so a published advert is
        dropped only when it is both unanswered and theirs.
        """
        current = self.advert_id(config)
        if current is not None and current != advert_id:
            return False
        self._cleanup(config)
        return True

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


def select_endpoint() -> DaemonEndpoint:
    """The control-channel strategy this platform serves on.

    A factory rather than a module singleton: the daemon and the proxy each build one
    at their composition root and hand it to everything below them, so substituting a
    strategy is an argument rather than a monkeypatch.

    The 2 strategies are imported here rather than at module scope, because each of
    them imports this abstraction: the dependency points inward everywhere except at
    this one composition line.
    """
    from camoufox_mcp.daemon.endpoint_loopback import LoopbackEndpoint
    from camoufox_mcp.daemon.endpoint_unix import UnixSocketEndpoint

    return LoopbackEndpoint() if IS_WINDOWS else UnixSocketEndpoint()
