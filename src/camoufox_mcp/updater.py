from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_S = 24 * 3600
_STAMP_NAME = ".update_check"


class BrowserSetupError(RuntimeError):
    """Raised when no usable Camoufox binary is available and it cannot be fetched."""


async def ensure_browser_present(config: ServerConfig) -> None:
    """Guarantee a usable Camoufox binary exists, blocking only on a cold install.

    This is on the startup critical path, so it never performs the (slow, network)
    version check: if a local binary already exists it returns immediately. Only the
    very first install — when no binary is present at all — blocks to download one.
    Honors ``CAMOUFOX_AUTO_UPDATE=false`` (then a missing binary is a hard error).
    """
    if _binary_present(config):
        return
    if not config.auto_update:
        raise BrowserSetupError(
            "No local Camoufox binary found and auto-update is disabled "
            "(CAMOUFOX_AUTO_UPDATE=false). Run `camoufox fetch` first."
        )
    try:
        await asyncio.to_thread(_update_browser)
        await asyncio.to_thread(_update_geoip)
    except Exception as exc:
        raise BrowserSetupError(
            f"Camoufox download failed and no local binary is present: {exc}"
        ) from exc
    _write_stamp(config)


def schedule_refresh(config: ServerConfig) -> asyncio.Task[None] | None:
    """Start a background binary + GeoIP refresh if one is due, else return ``None``.

    Throttled to at most once per ``_CHECK_INTERVAL_S`` (a timestamp file records the
    last successful check), so concurrent server starts don't each pay the version
    check. The refresh runs off the startup critical path, so the server is ready
    immediately; the caller owns the returned task and should cancel it on shutdown.
    """
    if not config.auto_update or not _is_due(config):
        return None
    return asyncio.create_task(_refresh(config))


async def _refresh(config: ServerConfig) -> None:
    try:
        await asyncio.to_thread(_update_browser)
        await asyncio.to_thread(_update_geoip)
        _write_stamp(config)
        logger.info("Camoufox binary and GeoIP database refreshed in background.")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Background Camoufox refresh failed; keeping local binary: %s", exc)


def _stamp_path(config: ServerConfig) -> Path:
    return config.data_dir / _STAMP_NAME


def _is_due(config: ServerConfig) -> bool:
    try:
        age = time.time() - _stamp_path(config).stat().st_mtime
    except OSError:
        return True
    return age > _CHECK_INTERVAL_S


def _write_stamp(config: ServerConfig) -> None:
    stamp = _stamp_path(config)
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.debug("Could not write update stamp", exc_info=True)


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
