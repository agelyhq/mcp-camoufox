"""What startup does about the browser build: the cold install, the pin, the refresh.

The parent side of auto-update. Every network fetch goes through a ``fetch`` callable,
:func:`fetch_in_child` unless a caller supplies its own, so nothing here prints, blocks
on a socket, or touches the process streams. The policy is unchanged: a cold install is
the only blocking step, the refresh is fail-open, non-blocking and throttled by a 24h
stamp that only a completed refresh writes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from camoufox_mcp.updater.builds import activate, binary_present
from camoufox_mcp.updater.child import fetch_in_child
from camoufox_mcp.updater.errors import BrowserSetupError

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.updater.child import Fetcher

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 24 * 3600
STAMP_NAME = ".update_check"


async def ensure_browser_present(config: ServerConfig, fetch: Fetcher = fetch_in_child) -> None:
    """Guarantee the configured Camoufox build exists, blocking only on a cold install.

    This is on the startup critical path, so it never performs the (slow, network)
    version check: if the build is already on disk it only re-asserts the pin (see
    :func:`_reassert_pin`, local and cheap) and returns. Only the very first install
    (when the pinned build is absent) blocks, on the fetch child, until it has exited.
    Honors ``CAMOUFOX_AUTO_UPDATE=false`` (then a missing build is a hard error).
    """
    _require_configured_binary(config)
    if binary_present(config):
        _reassert_pin(config)
        return
    if not config.auto_update:
        raise BrowserSetupError(
            f"Camoufox browser build {_wanted(config)} is not installed and auto-update "
            f"is disabled (CAMOUFOX_AUTO_UPDATE=false). Run `camoufox fetch {_wanted(config)}` "
            "first."
        )
    try:
        await fetch(config, "browser")
    except Exception as exc:
        raise BrowserSetupError(
            f"Camoufox download failed and build {_wanted(config)} is not present: {exc}"
        ) from exc
    _reassert_pin(config)
    if await _fetch_geoip(config, fetch):
        write_update_stamp(config)


def _require_configured_binary(config: ServerConfig) -> None:
    """Reject a ``CAMOUFOX_BINARY`` naming something that is not on disk.

    Camoufox gives ``executable_path`` precedence over the build it was told to launch, so
    a bad path is never recovered by fetching anything. Left to ``binary_present``, the
    start looked like a cold install: it downloaded the pinned build and made it ACTIVE,
    changing which build every other camoufox consumer on the machine gets, and the launch
    then failed anyway on the missing executable, with an error naming no path. A typo
    belongs in the same class as an unknown pin: named, and fatal.
    """
    if not config.camoufox_binary or Path(config.camoufox_binary).exists():
        return
    raise BrowserSetupError(
        f"CAMOUFOX_BINARY={config.camoufox_binary!r} does not exist. Correct the path, or "
        "unset CAMOUFOX_BINARY to use the build Camoufox manages itself."
    )


async def _fetch_geoip(config: ServerConfig, fetch: Fetcher) -> bool:
    """Download the GeoIP database, fail-open, reporting whether it landed.

    It only ever reaches a launch when a proxy is configured (``geoip_forced``), so a
    proxy-less install must not be refused over an asset it never reads. Sharing the
    browser download's ``try`` reported any GeoIP failure as "build X is not present"
    while build X was on disk and fine: fatal, and untrue.

    A ``False`` leaves the update stamp unwritten, so the background refresh this same
    start schedules retries the fetch, rather than the 24h throttle sitting on an asset
    we already know is missing.
    """
    try:
        await fetch(config, "geoip")
    except Exception as exc:
        logger.warning(
            "Camoufox GeoIP database download failed; starting without it. Sessions using "
            "CAMOUFOX_PROXY may report a timezone and locale that do not match the exit IP: %s",
            exc,
        )
        return False
    return True


def _reassert_pin(config: ServerConfig) -> None:
    """Make the pinned build the ACTIVE install, on every start, off the update throttle.

    Camoufox derives the spoofed Firefox version and the asset paths it reads from the
    *active* install, not from the binary a launch selects, so a pinned build that is
    present but inactive ships a user agent that does not match the browser actually
    running. Activation is a local, idempotent rewrite of one config key, so it must not
    sit behind the 24h network throttle: a machine whose active install drifted would
    otherwise spoof the wrong version for a full day.

    Skipped when ``CAMOUFOX_BINARY`` names an executable outright (the pin is ignored in
    that mode) or when no build is pinned. Fail-open: a machine that cannot rewrite the
    key still has a usable browser, and refusing to start is the worse outcome.
    """
    if config.camoufox_binary or not config.browser_version:
        return
    try:
        activate(config.browser_version)
    except Exception as exc:
        logger.warning(
            "Could not activate the pinned Camoufox build %s; the spoofed Firefox version "
            "may not match the browser that launches: %s",
            config.browser_version,
            exc,
        )


def schedule_refresh(
    config: ServerConfig, fetch: Fetcher = fetch_in_child
) -> asyncio.Task[None] | None:
    """Start a background build + GeoIP refresh if one is due, else return ``None``.

    Throttled to at most once per :data:`CHECK_INTERVAL_S` (a timestamp file records the
    last successful check), so concurrent server starts don't each pay the version
    check. The refresh runs off the startup critical path, so the server is ready
    immediately; the caller owns the returned task and cancels it on shutdown, which
    terminates the fetch child. With a build pinned, only the GeoIP database is ever
    refreshed.
    """
    if not config.auto_update or not _is_due(config):
        return None
    return asyncio.create_task(_refresh(config, fetch))


async def _refresh(config: ServerConfig, fetch: Fetcher) -> None:
    try:
        await fetch(config, "browser")
        _reassert_pin(config)
        await fetch(config, "geoip")
        write_update_stamp(config)
        logger.info("Camoufox browser and GeoIP database refreshed in background.")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Background Camoufox refresh failed; keeping local build: %s", exc)


def _wanted(config: ServerConfig) -> str:
    return config.browser_version or "latest"


def _stamp_path(config: ServerConfig) -> Path:
    return config.data_dir / STAMP_NAME


def _is_due(config: ServerConfig) -> bool:
    try:
        age = time.time() - _stamp_path(config).stat().st_mtime
    except OSError:
        return True
    return age > CHECK_INTERVAL_S


def write_update_stamp(config: ServerConfig) -> None:
    stamp = _stamp_path(config)
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.debug("Could not write update stamp", exc_info=True)
