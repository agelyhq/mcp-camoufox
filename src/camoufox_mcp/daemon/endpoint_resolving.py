"""Async HTTP clients that find the daemon again on every request.

A proxy lives for hours, and the daemon behind it can be replaced in that time: by this
proxy's own respawn or by another proxy's. A client built once around one resolved
address keeps calling that address forever, which on Windows is a dead port with a
stale token (every daemon binds a fresh port and draws a fresh token). The transport
here resolves the advert as each request leaves, so whichever daemon is advertised is
the one that gets the request, with its own token.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from camoufox_mcp.daemon.endpoint import DEFAULT_MCP_TIMEOUT, UNRESOLVED_BASE_URL

if TYPE_CHECKING:
    from collections.abc import Callable

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.daemon.endpoint import Conn, DaemonEndpoint


class ResolvingAsyncTransport(httpx.AsyncBaseTransport):
    """Send each request to the daemon advertised at the moment it is sent.

    No advert at all raises :class:`httpx.ConnectError`, the same proof of "nothing is
    there" a refused connection gives, so callers need only one rule. The inner
    transport (a connection pool) is kept while the advert names the same address, and
    replaced, the old one closed, when it names another.
    """

    def __init__(self, endpoint: DaemonEndpoint, config: ServerConfig) -> None:
        self._endpoint = endpoint
        self._config = config
        self._conn: Conn | None = None
        self._inner: httpx.AsyncBaseTransport | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        conn = self._endpoint.resolve(self._config)
        if conn is None:
            raise httpx.ConnectError("no camoufox daemon is advertised", request=request)
        inner = await self._inner_for(conn)
        target = httpx.URL(conn.base_url)
        request.url = request.url.copy_with(
            scheme=target.scheme, host=target.host, port=target.port
        )
        request.headers["Host"] = request.url.netloc.decode("ascii")
        request.headers.update(conn.auth_headers)
        return await inner.handle_async_request(request)

    async def aclose(self) -> None:
        if self._inner is not None:
            await self._inner.aclose()
            self._inner = None
            self._conn = None

    async def _inner_for(self, conn: Conn) -> httpx.AsyncBaseTransport:
        if self._inner is not None and conn == self._conn:
            return self._inner
        previous = self._inner
        self._inner = self._endpoint.async_transport(conn)
        self._conn = conn
        if previous is not None:
            await previous.aclose()
        return self._inner


def resolving_client(
    endpoint: DaemonEndpoint, config: ServerConfig, timeout: float
) -> httpx.AsyncClient:
    """An async client for the control routes of whichever daemon is advertised."""
    return httpx.AsyncClient(
        transport=ResolvingAsyncTransport(endpoint, config),
        base_url=UNRESOLVED_BASE_URL,
        timeout=timeout,
    )


def mcp_client_factory(
    endpoint: DaemonEndpoint, config: ServerConfig
) -> Callable[..., httpx.AsyncClient]:
    """The ``httpx_client_factory`` of the proxy's ``StreamableHttpTransport``.

    fastmcp calls it with ``headers``, ``auth``, ``follow_redirects`` and sometimes
    ``timeout``; every one is passed through, and only the transport is ours.
    """

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.setdefault("timeout", DEFAULT_MCP_TIMEOUT)
        return httpx.AsyncClient(transport=ResolvingAsyncTransport(endpoint, config), **kwargs)

    return factory
