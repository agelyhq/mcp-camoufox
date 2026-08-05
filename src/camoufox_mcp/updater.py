from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox.multiversion import InstalledVersion

    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_S = 24 * 3600
_STAMP_NAME = ".update_check"


class BrowserSetupError(RuntimeError):
    """Raised when no usable Camoufox binary is available and it cannot be fetched."""


async def ensure_browser_present(config: ServerConfig) -> None:
    """Guarantee the configured Camoufox build exists, blocking only on a cold install.

    This is on the startup critical path, so it never performs the (slow, network)
    version check: if the build is already on disk it only re-asserts the pin (see
    :func:`_reassert_pin`, local and cheap) and returns. Only the very first install
    (when the pinned build is absent) blocks to download it.
    Honors ``CAMOUFOX_AUTO_UPDATE=false`` (then a missing build is a hard error).
    """
    if binary_present(config):
        await _reassert_pin(config)
        return
    if not config.auto_update:
        raise BrowserSetupError(
            f"Camoufox browser build {_wanted(config)} is not installed and auto-update "
            f"is disabled (CAMOUFOX_AUTO_UPDATE=false). Run `camoufox fetch {_wanted(config)}` "
            "first."
        )
    try:
        await asyncio.to_thread(update_browser, config.browser_version)
        await asyncio.to_thread(update_geoip)
    except Exception as exc:
        raise BrowserSetupError(
            f"Camoufox download failed and build {_wanted(config)} is not present: {exc}"
        ) from exc
    write_update_stamp(config)


async def _reassert_pin(config: ServerConfig) -> None:
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
        await asyncio.to_thread(_activate, config.browser_version)
    except Exception as exc:
        logger.warning(
            "Could not activate the pinned Camoufox build %s; the spoofed Firefox version "
            "may not match the browser that launches: %s",
            config.browser_version,
            exc,
        )


def schedule_refresh(config: ServerConfig) -> asyncio.Task[None] | None:
    """Start a background build + GeoIP refresh if one is due, else return ``None``.

    Throttled to at most once per ``_CHECK_INTERVAL_S`` (a timestamp file records the
    last successful check), so concurrent server starts don't each pay the version
    check. The refresh runs off the startup critical path, so the server is ready
    immediately; the caller owns the returned task and should cancel it on shutdown.
    With a build pinned, only the GeoIP database is ever refreshed.
    """
    if not config.auto_update or not _is_due(config):
        return None
    return asyncio.create_task(_refresh(config))


async def _refresh(config: ServerConfig) -> None:
    try:
        await asyncio.to_thread(update_browser, config.browser_version)
        await asyncio.to_thread(update_geoip)
        write_update_stamp(config)
        logger.info("Camoufox browser and GeoIP database refreshed in background.")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Background Camoufox refresh failed; keeping local build: %s", exc)


def _wanted(config: ServerConfig) -> str:
    return config.browser_version or "latest"


def _stamp_path(config: ServerConfig) -> Path:
    return config.data_dir / _STAMP_NAME


def _is_due(config: ServerConfig) -> bool:
    try:
        age = time.time() - _stamp_path(config).stat().st_mtime
    except OSError:
        return True
    return age > _CHECK_INTERVAL_S


def write_update_stamp(config: ServerConfig) -> None:
    stamp = _stamp_path(config)
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.debug("Could not write update stamp", exc_info=True)


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
    if config.camoufox_binary:
        return Path(config.camoufox_binary).exists()
    if config.browser_version:
        if installed_build(config.browser_version) is not None:
            return True
        # Absent. Call camoufox_path() for its side effect only: it purges a pre-0.5
        # flat cache layout, which must happen before we install into the versioned
        # one or the stale copy is stranded forever.
        _any_binary_present()
        return False
    return _any_binary_present()


def _any_binary_present() -> bool:
    # camoufox_path() prints ("Cleaning old data...") when it purges an incompatible
    # cache, and this runs on the startup path outside any other guard, so silence
    # it here or the stdio MCP protocol framing is corrupted.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            from camoufox.pkgman import camoufox_path

            camoufox_path(download_if_missing=False)
            return True
        except Exception:
            return False


def update_browser(version: str | None) -> None:
    """Install ``version`` (idempotent), or chase the newest release when ``None``.

    A pin is a promise not to move: once the build is on disk this only re-asserts
    that it is the active one, and never contacts GitHub. Camoufox derives the
    spoofed Firefox version from the *active* install rather than from the binary it
    was told to launch, so an inactive pin would leak a mismatched user agent.
    """
    # Camoufox prints progress to stdout/stderr; silence it so the stdio MCP
    # protocol is never corrupted.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if version is None:
            from camoufox.__main__ import CamoufoxUpdate

            # i_know_what_im_doing skips a click.confirm() prompt on a prerelease,
            # which would read stdin, the MCP transport, and hang the server.
            CamoufoxUpdate().update(i_know_what_im_doing=True)
            return
        if installed_build(version) is None:
            install_build(version)
        _activate(version)


def install_build(version: str) -> None:
    from camoufox.pkgman import CamoufoxFetcher, list_available_versions

    for candidate in list_available_versions(include_prerelease=True):
        if candidate.version.full_string == version:
            CamoufoxFetcher(selected_version=candidate).install()
            return
    raise BrowserSetupError(
        f"Camoufox browser build {version!r} is not offered for this platform. "
        "Run `camoufox sync && camoufox list` to see the available builds, then set "
        "CAMOUFOX_BROWSER_VERSION to one of them."
    )


def _activate(version: str) -> None:
    from camoufox.multiversion import set_active

    installed = installed_build(version)
    if installed is not None and not installed.is_active:
        set_active(installed.relative_path)


def update_geoip() -> None:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from camoufox.geolocation import download_mmdb

        download_mmdb()
