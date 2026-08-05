from __future__ import annotations


class DaemonError(RuntimeError):
    """Base class for control-plane failures of the shared daemon."""


class DaemonSpawnError(DaemonError):
    """Raised when the shared daemon could not be started or did not become healthy.

    The message carries a tail of ``daemon.log`` so the failure is diagnosable from
    the proxy's stderr without opening another file.
    """


class SocketPathTooLongError(DaemonError):
    """Raised when the control socket path exceeds the AF_UNIX ``sun_path`` limit.

    Checked before binding so the daemon reports the limit and the offending path
    instead of dying on the kernel's opaque ``OSError``.
    """
