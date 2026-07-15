from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)


class BrowserSetupError(RuntimeError):
    """Raised when no usable Camoufox binary is available and it cannot be fetched."""


async def ensure_browser_ready(config: ServerConfig) -> None:
    """Fail-open startup update of the Camoufox binary and GeoIP database.

    Honors ``CAMOUFOX_AUTO_UPDATE=false``. On update failure the server still
    starts if a local binary exists (a warning is logged); it hard-fails only
    when no local binary is present at all.
    """
    if not config.auto_update:
        if not _binary_present(config):
            raise BrowserSetupError(
                "No local Camoufox binary found and auto-update is disabled "
                "(CAMOUFOX_AUTO_UPDATE=false). Run `camoufox fetch` first."
            )
        logger.info("Auto-update disabled; using local Camoufox binary.")
        return

    try:
        await asyncio.to_thread(_update_browser)
        await asyncio.to_thread(_update_geoip)
        logger.info("Camoufox binary and GeoIP database are up to date.")
    except Exception as exc:
        if _binary_present(config):
            logger.warning("Camoufox auto-update failed; continuing with local binary: %s", exc)
            return
        raise BrowserSetupError(
            f"Camoufox auto-update failed and no local binary is present: {exc}"
        ) from exc


def _binary_present(config: ServerConfig) -> bool:
    if config.camoufox_binary:
        return Path(config.camoufox_binary).exists()
    try:
        from camoufox.pkgman import camoufox_path

        camoufox_path(download_if_missing=False)
        return True
    except Exception:
        return False


def _update_browser() -> None:
    # CamoufoxUpdate() contacts GitHub and prints progress to stdout/stderr;
    # silence it so the stdio MCP protocol is never corrupted.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from camoufox.__main__ import CamoufoxUpdate

        CamoufoxUpdate().update()


def _update_geoip() -> None:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from camoufox.locale import download_mmdb

        download_mmdb()
