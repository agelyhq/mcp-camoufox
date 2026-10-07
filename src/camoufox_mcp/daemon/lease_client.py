"""The proxy's half of a lease: renewing it, releasing it, and what a renewal proves.

Every renewal doubles as the liveness probe. Its answer is one of 3 things, and only 3
outcomes count as proof that the daemon is gone: no advertised address at all, a
refused connection, and the daemon itself answering that it is exiting. A timeout or a server error is NOT proof: a cold browser launch
does block the daemon's event loop for a while, and condemning a daemon on a slow
answer would kill exactly the healthy long call the recovery watchdog must leave alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from camoufox_mcp.daemon.endpoint_resolving import resolving_client
from camoufox_mcp.daemon.errors import LeaseRejectedError
from camoufox_mcp.daemon.identity import DaemonInstance
from camoufox_mcp.daemon.lease_routes import CLOSING_STATUS

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.daemon.endpoint import DaemonEndpoint

logger = logging.getLogger(__name__)

_RENEW_TIMEOUT_S = 2.0
_RELEASE_TIMEOUT_S = 1.0
# A daemon from before leases existed answers the route with one of these. It is alive
# and keeps working; it just cannot say which process it is.
_NO_LEASE_ROUTE = frozenset({404, 405})


@dataclass(frozen=True)
class Alive:
    """The daemon granted the lease, and named the process it is."""

    instance: DaemonInstance


@dataclass(frozen=True)
class Gone:
    """Positive proof that nothing listens on the control address."""


@dataclass(frozen=True)
class Unknown:
    """No verdict: a timeout, a server error, or a daemon without leases."""


Probe = Alive | Gone | Unknown
GONE = Gone()
UNKNOWN = Unknown()


class LeaseClient:
    """Renews and releases one lease on whichever daemon is advertised."""

    def __init__(
        self,
        config: ServerConfig,
        endpoint: DaemonEndpoint,
        lease_id: str,
        ttl_s: float,
    ) -> None:
        self._lease_id = lease_id
        self._ttl_s = ttl_s
        self._client = resolving_client(endpoint, config, timeout=_RENEW_TIMEOUT_S)

    async def renew(self) -> Probe:
        """Grant or renew the lease; what the attempt proves about the daemon.

        Raises:
            LeaseRejectedError: the daemon answered and refused the request itself.
        """
        try:
            response = await self._client.post(
                "/lease", json={"id": self._lease_id, "ttl_s": self._ttl_s}
            )
        except httpx.ConnectError:
            return GONE
        except (httpx.HTTPError, OSError):
            return UNKNOWN
        if response.status_code in _NO_LEASE_ROUTE:
            return UNKNOWN
        if response.status_code == CLOSING_STATUS:
            return GONE if _closing(response) else UNKNOWN
        if 400 <= response.status_code < 500:
            raise LeaseRejectedError(
                f"the daemon refused the lease ({response.status_code}): {response.text[:200]}"
            )
        if response.status_code != 200:
            return UNKNOWN
        try:
            payload = response.json()
        except ValueError:
            return UNKNOWN
        instance = DaemonInstance.from_payload(payload)
        return UNKNOWN if instance is None else Alive(instance)

    async def release(self) -> None:
        """Release the lease at once, best effort: an unreleased lease still expires."""
        try:
            await self._client.delete(f"/lease/{self._lease_id}", timeout=_RELEASE_TIMEOUT_S)
        except (httpx.HTTPError, OSError):
            logger.debug("Releasing the daemon lease failed; it will expire", exc_info=True)

    async def aclose(self) -> None:
        await self._client.aclose()


def _closing(response: httpx.Response) -> bool:
    """True when the daemon said it is exiting: as good as gone, and about to be."""
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("closing") is True
