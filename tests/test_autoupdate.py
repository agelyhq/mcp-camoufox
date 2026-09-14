"""The startup download branch: the 24h throttle, the GeoIP asset, an unknown pin.

The pin's own behaviour (activation, and ``CAMOUFOX_BINARY`` winning over it) lives in
:mod:`tests.test_autoupdate_pin`. Shared stand-ins live in :mod:`tests.updater_harness`.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp import updater
from tests.updater_harness import (
    RecordingFetcher,
    config_for,
    make_installed,
    only_install_is,
    pinned_install,
)

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
    newest release and undo the pin: the fetcher receives the config the child is
    spawned with, and the pin is read off it.
    """
    from camoufox_mcp.config import DEFAULT_BROWSER_VERSION

    fetch = RecordingFetcher()
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    only_install_is(monkeypatch, pinned_install(data_dir, is_active=True))

    task = updater.schedule_refresh(config, fetch=fetch)
    assert task is not None, "first start (no stamp) should schedule a refresh"
    await task
    assert fetch.assets == ["browser", "geoip"]
    assert fetch.versions == [DEFAULT_BROWSER_VERSION, DEFAULT_BROWSER_VERSION]

    # The refresh stamped the data dir, and the throttle is what that stamp is for.
    assert updater.schedule_refresh(config, fetch=fetch) is None, (
        "second start within 24h must be throttled"
    )


async def test_a_failed_refresh_leaves_the_retry_due(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-open in both directions: a refused fetch neither raises nor writes the stamp.

    The stamp records a SUCCESSFUL check. Written on a failure it would park a missing
    asset behind the 24h throttle; and a crashed or refused refresh that raised out of
    its task would surface at shutdown, where the lifespan awaits it.
    """
    fetch = RecordingFetcher(failing=frozenset({"geoip"}))
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    only_install_is(monkeypatch, pinned_install(data_dir, is_active=True))

    task = updater.schedule_refresh(config, fetch=fetch)
    assert task is not None
    await task
    assert fetch.assets == ["browser", "geoip"]

    assert updater.schedule_refresh(config, fetch=fetch) is not None, (
        "a failed refresh must leave the next start due"
    )


async def test_autoupdate_disabled_never_schedules(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="false")
    assert updater.schedule_refresh(config, fetch=RecordingFetcher()) is None


async def test_a_geoip_failure_does_not_refuse_a_start(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GeoIP is fail-open: only a proxy session reads it, so it cannot block a start.

    It shared the browser download's ``try``, so any GeoIP failure surfaced as "Camoufox
    download failed and build X is not present" while build X was on disk and fine, and
    blocked a proxy-less user over an asset they never use. CLAUDE.md documents startup
    auto-update as fail-open; this branch was not.

    Teeth: the build is absent until the browser fetch "lands" it, so the start really
    is a cold install; the activation proves the parent then finished its half of the
    branch (the child fetches, the parent activates); and the refresh is still due
    afterwards, so the missing asset is retried instead of parked behind the 24h throttle.
    """
    installed = pinned_install(data_dir, is_active=False)
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    activated = only_install_is(monkeypatch, None)
    fetch = RecordingFetcher(
        failing=frozenset({"geoip"}),
        on_browser=lambda: make_installed(monkeypatch, installed),
    )

    await updater.ensure_browser_present(config, fetch=fetch)

    assert fetch.assets == ["browser", "geoip"]
    assert activated == [installed.relative_path]
    refresh = updater.schedule_refresh(config, fetch=fetch)
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
        await updater.ensure_browser_present(config, fetch=RecordingFetcher())


async def test_the_real_fetch_child_fails_in_one_line(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child the server spawns resolves, runs offline to a clean failure, and reports it.

    Every other test here hands in a stand-in fetcher, so this is the one place the
    ``python -m camoufox_mcp.updater.fetch`` entry is proved runnable. A refused loopback
    proxy makes the download fail fast, and the failure must arrive as the exception
    that ended the child, not as a traceback: the parent appends it to the server log.
    """
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)

    with pytest.raises(updater.FetchError) as raised:
        await updater.fetch_in_child(config, "geoip")

    message = str(raised.value)
    assert message.startswith("geoip fetch exited with status 1: "), message
    assert "Traceback" not in message
    assert "127.0.0.1" in message, "the child's own error must reach the parent"


def test_camoufox_update_entrypoints_resolve() -> None:
    """Every camoufox symbol the updater imports lazily must still exist.

    These imports live inside functions whose failures are swallowed on purpose
    (the refresh is fail-open), so a rename upstream would silently stop all
    updating instead of raising. ``download_mmdb`` already moved once, from
    ``camoufox.locale`` to ``camoufox.geolocation``, between 0.4 and 0.5.
    """
    from camoufox.__main__ import CamoufoxUpdate
    from camoufox.geolocation import download_mmdb
    from camoufox.multiversion import get_active_path, list_installed, set_active
    from camoufox.pkgman import CamoufoxFetcher, Version, camoufox_path, list_available_versions

    for symbol in (
        CamoufoxUpdate,
        download_mmdb,
        get_active_path,
        list_installed,
        set_active,
        CamoufoxFetcher,
        camoufox_path,
        list_available_versions,
        Version.from_path,
        Version.is_supported,
    ):
        assert callable(symbol)
