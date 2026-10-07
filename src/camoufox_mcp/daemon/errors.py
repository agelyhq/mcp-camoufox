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


class LeaseLimitError(DaemonError):
    """Raised when a lease is requested while the daemon already holds its maximum.

    A bound on the table, so a runaway client cannot grow the daemon's memory without
    end: each proxy holds exactly 1 lease, and no machine runs hundreds of them.
    """


class LeaseClosedError(DaemonError):
    """Raised when a lease is requested from a daemon that has decided to exit.

    Granting it would hand a proxy a daemon that is about to vanish under it, so a
    closing daemon refuses every new lease and renewal from the moment it decides.
    """


class LeaseRejectedError(DaemonError):
    """Raised when the daemon refuses a lease request as malformed or unauthorized.

    Distinct from "no daemon answers": the daemon is there and said no, which is a
    defect on this side (a bad body, a stale token) rather than a dead daemon.
    """
