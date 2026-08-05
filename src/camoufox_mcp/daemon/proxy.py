from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import (
    FastMCPProxy,
    ProxyProvider,
    StatefulProxyClient,
)

from camoufox_mcp.bootstrap import SERVER_INSTRUCTIONS, SERVER_NAME
from camoufox_mcp.daemon.endpoint import select_endpoint
from camoufox_mcp.daemon.errors import DaemonSpawnError
from camoufox_mcp.daemon.recovery import DaemonRecovery, DaemonRecoveryMiddleware
from camoufox_mcp.daemon.spawn import ensure_daemon

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.daemon.endpoint import DaemonEndpoint

_CACHE_TTL_ATTR = "_cache_ttl"


class ProxyCacheError(RuntimeError):
    """Raised when the fastmcp ``ProxyProvider`` no longer exposes its cache knob.

    A plain ``setattr`` would silently create a dead attribute and leave the real
    list cache active, so a fresh proxy could serve a stale tool list. We fail loud
    instead of degrading silently on a fastmcp upgrade that renames the field.
    """


def run_proxy(config: ServerConfig) -> None:
    """Ensure the shared daemon is up, then serve stdio by proxying to it.

    The proxy's composition root: the platform control-channel strategy is built here,
    once, and handed to everything that reaches the daemon.
    """
    endpoint = select_endpoint()
    ensure_daemon(config, endpoint)
    build_proxy(config, endpoint).run(transport="stdio")


def build_proxy(config: ServerConfig, endpoint: DaemonEndpoint) -> FastMCP:
    """A stdio FastMCP proxy forwarding to the daemon's control channel.

    One persistent backend session per downstream stdio connection
    (:class:`StatefulProxyClient`), tool-list caching disabled so a freshly started
    proxy never serves a stale tool list after a daemon code reload, and a recovery
    middleware that respawns a daemon which dies mid-conversation. The transport
    (Unix socket on POSIX, authenticated loopback on Windows) is supplied by the
    injected ``endpoint``.
    """
    conn = endpoint.resolve(config)
    if conn is None:
        raise DaemonSpawnError("daemon endpoint disappeared after ensure_daemon")
    transport = StreamableHttpTransport(
        endpoint.mcp_url(conn),
        httpx_client_factory=endpoint.mcp_client_factory(conn),
    )
    client = StatefulProxyClient(transport)
    proxy = FastMCPProxy(
        client_factory=client.new_stateful,
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
    )
    _disable_list_cache(proxy)
    _install_recovery(proxy, config, endpoint, client)
    return proxy


def _install_recovery(
    proxy: FastMCPProxy,
    config: ServerConfig,
    endpoint: DaemonEndpoint,
    client: StatefulProxyClient,
) -> None:
    """Put the recovery middleware outermost, ahead of fastmcp's own proxy middleware.

    fastmcp runs ``middleware[0]`` outermost, and ``FastMCPProxy`` appends its
    ``ProxyInitializeMiddleware``, which opens the backend session inside its
    ``on_initialize`` hook. Appending would leave that connect attempt (the very
    first thing a dead daemon breaks) outside our reach, so we insert at the front.
    """
    proxy.middleware.insert(0, DaemonRecoveryMiddleware(DaemonRecovery(config, endpoint), client))


def _disable_list_cache(proxy: FastMCPProxy) -> None:
    """Force every ``ProxyProvider`` to skip list caching (``cache_ttl = 0``).

    fastmcp stores the TTL in the private ``_cache_ttl`` attribute (settable only
    after construction, since ``FastMCPProxy`` builds the provider itself with a
    default TTL). We verify the attribute exists before overwriting it and that at
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
