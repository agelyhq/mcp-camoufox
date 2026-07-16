from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import (
    FastMCPProxy,
    ProxyProvider,
    StatefulProxyClient,
)

from camoufox_mcp.bootstrap import SERVER_INSTRUCTIONS, SERVER_NAME
from camoufox_mcp.daemon.spawn import ensure_daemon

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from camoufox_mcp.config import ServerConfig

_BASE_URL = "http://camoufox-daemon/mcp"

_CACHE_TTL_ATTR = "_cache_ttl"


class ProxyCacheError(RuntimeError):
    """Raised when the fastmcp ``ProxyProvider`` no longer exposes its cache knob.

    A plain ``setattr`` would silently create a dead attribute and leave the real
    list cache active, so a fresh proxy could serve a stale tool list. We fail loud
    instead of degrading silently on a fastmcp upgrade that renames the field.
    """


def run_proxy(config: ServerConfig) -> None:
    """Ensure the shared daemon is up, then serve stdio by proxying to it."""
    ensure_daemon(config)
    build_proxy(config).run(transport="stdio")


def build_proxy(config: ServerConfig) -> FastMCP:
    """A stdio FastMCP proxy forwarding to the daemon over its Unix domain socket.

    One persistent backend session per downstream stdio connection
    (:class:`StatefulProxyClient`), and tool-list caching disabled so a freshly
    started proxy never serves a stale tool list after a daemon code reload.
    """
    transport = StreamableHttpTransport(
        _BASE_URL,
        httpx_client_factory=_uds_client_factory(str(config.daemon_socket_path)),
    )
    client = StatefulProxyClient(transport)
    proxy = FastMCPProxy(
        client_factory=client.new_stateful,
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
    )
    _disable_list_cache(proxy)
    return proxy


def _uds_client_factory(socket_path: str) -> Callable[..., httpx.AsyncClient]:
    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.setdefault("timeout", httpx.Timeout(30.0, read=300.0))
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        return httpx.AsyncClient(transport=transport, **kwargs)

    return factory


def _disable_list_cache(proxy: FastMCPProxy) -> None:
    """Force every ``ProxyProvider`` to skip list caching (``cache_ttl = 0``).

    fastmcp 3.4.4 stores the TTL in the private ``_cache_ttl`` attribute (settable
    only after construction, since ``FastMCPProxy`` builds the provider itself with
    a default TTL). We verify the attribute exists before overwriting it and that at
    least one provider was found, raising :class:`ProxyCacheError` otherwise so a
    fastmcp rename surfaces immediately instead of silently re-enabling the cache.
    """
    disabled = 0
    for provider in proxy.providers:
        if isinstance(provider, ProxyProvider):
            if not hasattr(provider, _CACHE_TTL_ATTR):
                raise ProxyCacheError(
                    f"fastmcp ProxyProvider no longer exposes '{_CACHE_TTL_ATTR}'; "
                    "cannot disable tool-list caching"
                )
            setattr(provider, _CACHE_TTL_ATTR, 0)
            disabled += 1
    if disabled == 0:
        raise ProxyCacheError("no ProxyProvider on the FastMCPProxy; cannot disable list caching")
