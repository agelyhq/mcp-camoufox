"""What this process knows about the Camoufox builds on disk, without printing or fetching.

Everything here reads the ``browsers/`` tree and Camoufox's own config file, or rewrites
one key of that file. Nothing here reaches the network, and nothing here calls a
camoufox function that prints: those run in the fetch child (:mod:`.fetch`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox.multiversion import InstalledVersion

    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)


def installed_build(version: str) -> InstalledVersion | None:
    """The local install of ``version``, or ``None`` when it is not on disk.

    Reads only the ``browsers/`` tree, so it is offline and cheap. A cache we cannot
    read is reported as "not installed", which routes into the (re)install path.
    """
    try:
        from camoufox.multiversion import list_installed

        for installed in list_installed():
            if installed.version.full_string == version:
                return installed
    except Exception:
        logger.debug("Could not enumerate installed Camoufox builds", exc_info=True)
    return None


def binary_present(config: ServerConfig) -> bool:
    """Whether the build this config launches is on disk, decided without a fetch."""
    if config.camoufox_binary:
        return Path(config.camoufox_binary).exists()
    if config.browser_version:
        return installed_build(config.browser_version) is not None
    return active_build_supported()


def active_build_supported() -> bool:
    """Whether Camoufox's ACTIVE install is one this camoufox version can launch.

    The same question ``camoufox_path(download_if_missing=False)`` answers, asked of the
    2 reads behind it (the active key and that build's ``version.json``) rather than of
    the function: ``camoufox_path`` also purges a pre-0.5 cache layout and prints while
    it does, and nothing in this process may print. The purge still happens, in the fetch
    child, before it installs into the versioned layout.
    """
    try:
        from camoufox.multiversion import get_active_path
        from camoufox.pkgman import Version

        active = get_active_path()
        return active is not None and Version.from_path(active).is_supported()
    except Exception:
        logger.debug("Could not read the active Camoufox build", exc_info=True)
        return False


def activate(version: str) -> None:
    """Make ``version`` the ACTIVE install when it is on disk and not already active.

    A local, idempotent rewrite of one config key. Camoufox derives the spoofed Firefox
    version and the asset paths it reads from the active install, not from the binary a
    launch selects, so a present-but-inactive pin ships a mismatched user agent.
    """
    from camoufox.multiversion import set_active

    installed = installed_build(version)
    if installed is not None and not installed.is_active:
        set_active(installed.relative_path)
