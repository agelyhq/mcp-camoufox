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


def local_identity(config: ServerConfig) -> DaemonIdentity:
    """Identity of the code and configuration running in this process."""
    return DaemonIdentity(
        version=pkg_version(),
        code_path=code_path(),
        data_dir=str(config.data_dir.resolve()),
    )
