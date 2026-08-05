"""Filesystem layout of the daemon control plane, derived from ``config.data_dir``.

The daemon is opt-in, and the names of its socket, advert, lock and log are a daemon
concern: ``ServerConfig`` carries the data root and the env parsing, this module
carries what the control plane puts under it. Everything here is a pure function of
the config, so a path is reproducible from a :class:`ServerConfig` alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.config import ensure_private_dir

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig

_DIR_NAME = "daemon"
_SOCKET_NAME = "daemon.sock"
_ENDPOINT_NAME = "daemon.endpoint"
_LOCK_NAME = "daemon.lock"
_LOG_NAME = "daemon.log"


def daemon_dir(config: ServerConfig) -> Path:
    """Private (0o700) home of the daemon socket, advert, lock and log."""
    return config.data_dir / _DIR_NAME


def socket_path(config: ServerConfig) -> Path:
    """The in-data-dir Unix socket address, used when there is no runtime dir."""
    return daemon_dir(config) / _SOCKET_NAME


def endpoint_path(config: ServerConfig) -> Path:
    """Windows advert file: the daemon's loopback host, port and bearer token."""
    return daemon_dir(config) / _ENDPOINT_NAME


def lock_path(config: ServerConfig) -> Path:
    """Exclusive spawn lock, so concurrent proxies never double-spawn a daemon."""
    return daemon_dir(config) / _LOCK_NAME


def log_path(config: ServerConfig) -> Path:
    """Where the detached daemon's stdout and stderr are redirected."""
    return daemon_dir(config) / _LOG_NAME


def ensure_daemon_dir(config: ServerConfig) -> Path:
    """Create ``<data_dir>/daemon/`` restricted to the owner, then return it.

    The control channel's advert lives here: on POSIX a 0o700 parent keeps the Unix
    socket unreachable during the window before the endpoint tightens it to 0o600,
    and on Windows it holds the bearer-token ``daemon.endpoint`` file. ``chmod``
    re-runs after ``mkdir`` to defeat a permissive umask on a pre-existing directory
    (a near-no-op on Windows, where the token is the real boundary). Called by both
    the daemon (before binding) and the spawner.
    """
    ensure_private_dir(config.data_dir)
    return ensure_private_dir(daemon_dir(config))
