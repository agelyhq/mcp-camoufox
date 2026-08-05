"""Where the POSIX control socket lives, and why it is not under the data dir.

An AF_UNIX address is a fixed ``sun_path`` buffer, so a socket under a deep
``CAMOUFOX_DATA_DIR`` simply cannot be bound: the daemon would die on an opaque
``OSError`` before serving anything. The runtime dir (``ServerConfig.runtime_dir``,
parsed from ``XDG_RUNTIME_DIR``) is short, per user and already owner-only, so the
socket goes there while profiles, telemetry, the spawn lock and ``daemon.log`` all
stay in the data dir.

Discovery stays anchored in the data dir all the same. The socket name carries a
digest of the data dir, so two servers configured with different data dirs never
meet on one control channel, and a running daemon records the address it bound in
``<data_dir>/daemon/daemon.address``. That pointer is what a proxy reads first:
processes do not always agree on the runtime dir (a desktop client and a service
manager have different environments), and a proxy that derived a different address
would start a second daemon on the same profiles.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from camoufox_mcp.config import ensure_private_dir
from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.errors import SocketPathTooLongError

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig

# sizeof(sun_path) is 104 on macOS/BSD and 108 on Linux, terminator included.
_SUN_PATH_BYTES = 104 if sys.platform == "darwin" else 108
MAX_SOCKET_PATH_BYTES = _SUN_PATH_BYTES - 1

_RUNTIME_SUBDIR = "camoufox-mcp"
_ADDRESS_FILE = "daemon.address"
_TAG_CHARS = 16


def published_socket_path(config: ServerConfig) -> Path:
    """Where a daemon for this data dir is listening, pointer first.

    A running daemon's own record of its address beats what this process would
    derive, so an environment without ``XDG_RUNTIME_DIR`` still finds the daemon
    started by one that had it. A pointer to a socket that no longer exists simply
    resolves to nothing and is rewritten by the next daemon.
    """
    pointer = _read_address_pointer(config)
    return pointer if pointer is not None else daemon_socket_path(config)


def publish_socket_path(config: ServerConfig, path: Path) -> None:
    """Record, in the data dir, the address this daemon just bound."""
    paths.ensure_daemon_dir(config)
    target = paths.daemon_dir(config) / _ADDRESS_FILE
    tmp = target.with_name(f"{_ADDRESS_FILE}.tmp")
    tmp.write_text(str(path), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    os.replace(tmp, target)


def unpublish_socket_path(config: ServerConfig) -> None:
    """Drop the address pointer, so a stale one never outlives its daemon."""
    with contextlib.suppress(OSError):
        (paths.daemon_dir(config) / _ADDRESS_FILE).unlink()


def _read_address_pointer(config: ServerConfig) -> Path | None:
    try:
        raw = (paths.daemon_dir(config) / _ADDRESS_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(raw) if raw else None


def daemon_socket_path(config: ServerConfig) -> Path:
    """Address a daemon started here and now would bind, runtime dir first.

    Falls back to ``<data_dir>/daemon/daemon.sock`` when the config carries no usable
    runtime dir, which is also the only case where the length check can fail. Pure
    and deterministic: same config, same answer.
    """
    root = config.runtime_dir
    if root is None:
        return paths.socket_path(config)
    return root / _RUNTIME_SUBDIR / f"{_data_dir_tag(config)}.sock"


def ensure_socket_dir(config: ServerConfig) -> Path:
    """Create the owner-only directory holding the control socket, and return the path.

    The single way that directory comes into existence: :meth:`UnixSocketEndpoint.bind`
    goes through it, so the mode is never a bind-site detail that a second call site
    could get wrong.
    """
    path = daemon_socket_path(config)
    ensure_private_dir(path.parent)
    return path


def check_socket_path(path: Path) -> None:
    """Raise before binding when ``path`` cannot fit in an AF_UNIX address."""
    length = len(os.fsencode(str(path)))
    if length > MAX_SOCKET_PATH_BYTES:
        raise SocketPathTooLongError(
            f"the daemon control socket path is {length} bytes, over the "
            f"{MAX_SOCKET_PATH_BYTES}-byte AF_UNIX sun_path limit: {path}. "
            "Set XDG_RUNTIME_DIR to a short per-user directory, or point "
            "CAMOUFOX_DATA_DIR at a shorter path."
        )


def _data_dir_tag(config: ServerConfig) -> str:
    """Short stand-in for the data dir, so distinct configurations never collide."""
    resolved = os.fsencode(str(config.data_dir.resolve()))
    return hashlib.sha256(resolved).hexdigest()[:_TAG_CHARS]
