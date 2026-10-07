from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import camoufox_mcp

if TYPE_CHECKING:
    from collections.abc import Mapping

    from camoufox_mcp.config import ServerConfig

_PACKAGE = "mcp-camoufox"


def pkg_version() -> str:
    """Installed ``mcp-camoufox`` version, or ``"unknown"`` when not packaged."""
    try:
        return importlib.metadata.version(_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def code_path() -> str:
    """Absolute path of the imported ``camoufox_mcp`` package __init__."""
    return str(Path(camoufox_mcp.__file__).resolve())


@dataclass(frozen=True)
class DaemonIdentity:
    """What makes a running daemon interchangeable with the code in this process.

    The data dir belongs here as much as the code does: the control socket no longer
    lives under it, so a matching version and code path alone would let a proxy adopt
    a daemon serving someone else's profiles.
    """

    version: str
    code_path: str
    data_dir: str

    def matches(self, health: Mapping[str, object]) -> bool:
        """True when a ``/health`` payload reports this exact identity."""
        return (
            health.get("version") == self.version
            and health.get("code_path") == self.code_path
            and health.get("data_dir") == self.data_dir
        )

    def as_health(self) -> dict[str, str]:
        """The identity fields as published on ``/health``."""
        return {
            "version": self.version,
            "code_path": self.code_path,
            "data_dir": self.data_dir,
        }


@dataclass(frozen=True)
class DaemonInstance:
    """One daemon process: its pid plus its start time, so a recycled pid is told apart.

    Where :class:`DaemonIdentity` says whether a daemon runs the same code, this says
    whether it is the same PROCESS. Both ``/health`` and ``/lease`` publish it, and a
    proxy that sees it change knows the daemon it was talking to is gone.
    """

    pid: int
    started_at: str

    @classmethod
    def from_payload(cls, payload: object) -> DaemonInstance | None:
        """The instance a ``/health`` or ``/lease`` reply names, or None when malformed."""
        if not isinstance(payload, dict):
            return None
        pid = payload.get("pid")
        started_at = payload.get("started_at")
        if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(started_at, str):
            return None
        return cls(pid=pid, started_at=started_at)

    def as_payload(self) -> dict[str, object]:
        """The fields as published on the control channel."""
        return {"pid": self.pid, "started_at": self.started_at}


def local_identity(config: ServerConfig) -> DaemonIdentity:
    """Identity of the code and configuration running in this process."""
    return DaemonIdentity(
        version=pkg_version(),
        code_path=code_path(),
        data_dir=str(config.data_dir.resolve()),
    )
