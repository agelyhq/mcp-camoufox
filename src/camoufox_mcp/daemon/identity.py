from __future__ import annotations

import importlib.metadata
from pathlib import Path

import camoufox_mcp

_PACKAGE = "camoufox-mcp"


def pkg_version() -> str:
    """Installed ``camoufox-mcp`` version, or ``"unknown"`` when not packaged."""
    try:
        return importlib.metadata.version(_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def code_path() -> str:
    """Absolute path of the imported ``camoufox_mcp`` package __init__."""
    return str(Path(camoufox_mcp.__file__).resolve())


def local_identity() -> tuple[str, str]:
    """(version, code_path) of the code running in this process."""
    return pkg_version(), code_path()


def health_matches_identity(health: dict[str, object], identity: tuple[str, str]) -> bool:
    """True when a /health payload reports the same version AND code path we run."""
    version, path = identity
    return health.get("version") == version and health.get("code_path") == path
