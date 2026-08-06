"""The startup download branch: the 24h throttle, the GeoIP asset, an unknown pin.

The pin's own behaviour (activation, and ``CAMOUFOX_BINARY`` winning over it) lives in
:mod:`tests.test_autoupdate_pin`. Shared stand-ins live in :mod:`tests.updater_harness`.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, Any

import pytest

from camoufox_mcp import updater
from tests.updater_harness import config_for, forbid_download, only_install_is, pinned_install

if TYPE_CHECKING:
    from pathlib import Path


async def test_autoupdate_refreshes_once_then_throttles(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First start refreshes in the background; a start within 24h is throttled.

    This is the concurrency fix: the slow GitHub version check runs at most once
    per interval and never blocks the server from becoming ready, so many
    concurrent server starts don't each stall on it. The refresh must also carry
    the pinned build through, or the background task would quietly re-chase the
    newest release and undo the pin.
    """
    from camoufox_mcp.config import DEFAULT_BROWSER_VERSION

    calls: list[Any] = []
    monkeypatch.setattr(updater, "update_browser", lambda version: calls.append(version))
    monkeypatch.setattr(updater, "update_geoip", lambda: calls.append("geoip"))
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")

    task = updater.schedule_refresh(config)
    assert task is not None, "first start (no stamp) should schedule a refresh"
    await task
    assert calls == [DEFAULT_BROWSER_VERSION, "geoip"]

    # The refresh stamped the data dir, and the throttle is what that stamp is for.
    assert updater.schedule_refresh(config) is None, "second start within 24h must be throttled"


async def test_autoupdate_disabled_never_schedules(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="false")
    assert updater.schedule_refresh(config) is None


async def test_a_geoip_failure_does_not_refuse_a_start(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GeoIP is fail-open: only a proxy session reads it, so it cannot block a start.

    It shared the browser download's ``try``, so any GeoIP failure surfaced as "Camoufox
    download failed and build X is not present" while build X was on disk and fine, and
    blocked a proxy-less user over an asset they never use. CLAUDE.md documents startup
    auto-update as fail-open; this branch was not.

    Teeth: the activation proves the browser half of the branch ran to completion, so the
    start is not passing by skipping the work; and the refresh is still due afterwards, so
    the missing asset is retried instead of parked behind the 24h throttle. Only the 2
    entry points that must not run are trapped, since ``update_browser`` is the work being
    asserted.
    """
    installed = pinned_install(data_dir, is_active=False)
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    activated = only_install_is(monkeypatch, installed)
    monkeypatch.setattr(updater, "binary_present", lambda _config: False)
    monkeypatch.setattr(updater, "install_build", forbid_download)
    monkeypatch.setattr(updater, "update_geoip", forbid_download)

    await updater.ensure_browser_present(config)

    assert activated == [installed.relative_path]
    refresh = updater.schedule_refresh(config)
    assert refresh is not None, "an unstamped start must leave the GeoIP retry due"
    refresh.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await refresh


async def test_unknown_pinned_build_fails_loudly(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that is neither installed nor installable is a hard, named error.

    With auto-update off there is nothing to fall back to, and silently launching
    some other build is exactly the drift the pin exists to stop.
    """
    config = config_for(
        data_dir,
        monkeypatch,
        CAMOUFOX_AUTO_UPDATE="false",
        CAMOUFOX_BROWSER_VERSION="1.2.3-beta.999",
    )

    with pytest.raises(updater.BrowserSetupError, match=re.escape("1.2.3-beta.999")):
        await updater.ensure_browser_present(config)


def test_camoufox_update_entrypoints_resolve() -> None:
    """Every camoufox symbol the updater imports lazily must still exist.

    These imports live inside functions whose failures are swallowed on purpose
    (the refresh is fail-open), so a rename upstream would silently stop all
    updating instead of raising. ``download_mmdb`` already moved once, from
    ``camoufox.locale`` to ``camoufox.geolocation``, between 0.4 and 0.5.
    """
    from camoufox.__main__ import CamoufoxUpdate
    from camoufox.geolocation import download_mmdb
    from camoufox.multiversion import list_installed, set_active
    from camoufox.pkgman import CamoufoxFetcher, camoufox_path, list_available_versions

    for symbol in (
        CamoufoxUpdate,
        download_mmdb,
        list_installed,
        set_active,
        CamoufoxFetcher,
        camoufox_path,
        list_available_versions,
    ):
        assert callable(symbol)
