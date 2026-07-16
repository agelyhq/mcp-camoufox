from __future__ import annotations


class DaemonSpawnError(RuntimeError):
    """Raised when the shared daemon could not be started or did not become healthy.

    The message carries a tail of ``daemon.log`` so the failure is diagnosable from
    the proxy's stderr without opening another file.
    """
