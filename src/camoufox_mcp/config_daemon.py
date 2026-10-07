"""Parsers for the shared-daemon variables. Pure: ``config.py`` reads the environment."""

from __future__ import annotations

import math

DEFAULT_DAEMON_TTL_S = 1800
DEFAULT_LEASE_INTERVAL_S = 30.0
# A proxy renewing less often than this would keep a dead proxy's daemon alive for
# a quarter of an hour (its lease outlives 3 intervals).
MAX_LEASE_INTERVAL_S = 300.0


def parse_daemon_ttl(raw: str | None) -> int:
    """``CAMOUFOX_DAEMON_TTL``: idle seconds before the daemon exits, a positive integer."""
    if raw is None or raw.strip() == "":
        return DEFAULT_DAEMON_TTL_S
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid CAMOUFOX_DAEMON_TTL={raw!r}; expected a positive integer"
        ) from exc
    if value <= 0:
        raise ValueError(f"Invalid CAMOUFOX_DAEMON_TTL={raw!r}; must be > 0")
    return value


def parse_lease_interval(raw: str | None) -> float:
    """``CAMOUFOX_DAEMON_LEASE_INTERVAL``: seconds between a proxy's lease renewals."""
    if raw is None or raw.strip() == "":
        return DEFAULT_LEASE_INTERVAL_S
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid CAMOUFOX_DAEMON_LEASE_INTERVAL={raw!r}; expected a number of seconds"
        ) from exc
    if not math.isfinite(value) or not 0 < value <= MAX_LEASE_INTERVAL_S:
        raise ValueError(
            f"Invalid CAMOUFOX_DAEMON_LEASE_INTERVAL={raw!r}; "
            f"must be > 0 and <= {MAX_LEASE_INTERVAL_S:.0f}"
        )
    return value
