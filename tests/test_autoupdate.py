from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from camoufox_mcp import updater
from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig

# The 3 entry points that can reach the network. Every "this start downloads nothing"
# test traps all 3, because trapping only the one it expects to be skipped would pass
# just as green if the call had moved to a sibling.
_DOWNLOAD_ENTRY_POINTS = ("update_browser", "update_geoip", "install_build")


def _config(data_dir: Path, monkeypatch: pytest.MonkeyPatch, **overrides: str) -> ServerConfig:
    isolate_camoufox_env(monkeypatch, data_dir, **overrides)
    from camoufox_mcp.config import ServerConfig

    return ServerConfig.from_env()


def _forbid_download(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("download attempted")


@pytest.fixture
def forbid_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Booby-trap every path to the network, so a start that fetches anything fails."""
    for name in _DOWNLOAD_ENTRY_POINTS:
        monkeypatch.setattr(updater, name, _forbid_download)


def _pinned_install(data_dir: Path, *, is_active: bool) -> Any:
    """A stand-in for the pinned build as ``camoufox.multiversion`` would report it.

    Built from the real ``InstalledVersion``/``Version`` classes so ``full_string`` and
    ``relative_path`` are computed by upstream's own code, and synthetic so the test
    never depends on (or mutates) what this machine happens to have installed.
    """
    from camoufox.multiversion import InstalledVersion
    from camoufox.pkgman import Version

    return InstalledVersion(
        repo_name="pinned",
        version=Version(build="beta.28", version="152.0.4"),
        path=data_dir / "browsers" / "pinned" / "152.0.4-beta.28",
        is_active=is_active,
    )


def _only_install_is(monkeypatch: pytest.MonkeyPatch, installed: Any) -> list[str]:
    """Make ``installed`` the machine's whole install list; return what gets activated.

    Only the 2 upstream boundary functions are replaced, so ``binary_present``,
    ``installed_build`` and ``_activate`` all run for real, and no test rewrites the
    shared camoufox config on the developer's machine.
    """
    from camoufox import multiversion

    activated: list[str] = []
    monkeypatch.setattr(multiversion, "list_installed", lambda: [installed])
    monkeypatch.setattr(multiversion, "set_active", activated.append)
    return activated


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
    config = _config(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")

    task = updater.schedule_refresh(config)
    assert task is not None, "first start (no stamp) should schedule a refresh"
    await task
    assert calls == [DEFAULT_BROWSER_VERSION, "geoip"]

    # The refresh stamped the data dir, and the throttle is what that stamp is for.
    assert updater.schedule_refresh(config) is None, "second start within 24h must be throttled"


async def test_autoupdate_disabled_never_schedules(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="false")
    assert updater.schedule_refresh(config) is None


async def test_pinned_build_present_needs_no_download(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, forbid_downloads: None
) -> None:
    """A pin means "do not move": startup must never reach for the network.

    The whole body used to be setup. Booby-trapping the download and then calling the
    function asserts nothing on its own: a gutted ``ensure_browser_present`` that did
    no work at all would pass just as green, and so would a machine where the pinned
    build is missing but some other early return fires. Two things make it real. The
    precondition pins WHY the download is skipped, and the control below proves the
    traps can fire at all.
    """
    from camoufox import multiversion

    from camoufox_mcp.config import DEFAULT_BROWSER_VERSION

    config = _config(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")

    # The early return is only meaningful if the pinned build really is installed;
    # otherwise this passes for a reason that has nothing to do with the pin.
    assert updater.installed_build(DEFAULT_BROWSER_VERSION) is not None, (
        f"the suite's pinned build {DEFAULT_BROWSER_VERSION} is not installed"
    )

    # This one runs against the machine's real install list, and the startup path now
    # re-asserts the pin, so neuter the only call that could write to the shared
    # camoufox config. No assertion on it: activating is legitimate here, mutating the
    # developer's machine from a test is not.
    monkeypatch.setattr(multiversion, "set_active", lambda _relative_path: None)

    await updater.ensure_browser_present(config)


@pytest.mark.parametrize("auto_update", ["true", "false"])
async def test_pinned_build_is_activated_on_a_throttled_start(
    auto_update: str, data_dir: Path, monkeypatch: pytest.MonkeyPatch, forbid_downloads: None
) -> None:
    """A present-but-inactive pin is activated at startup, not 24h later.

    Camoufox reads the spoofed Firefox version off the ACTIVE install rather than off
    the binary the launch selects, so an inactive pin sends a user agent that does not
    match the browser running. Activation used to be reachable only through the
    background refresh, which is throttled to once per 24h, so the mismatch could last a
    whole day: this pins it to every start.

    Teeth: the stamp is written first, so the throttle is provably closed (asserted) and
    the activation cannot be coming from the refresh; the 3 download entry points are
    booby-trapped, so nothing reaches the network; and only the 2 upstream boundary
    functions are replaced, so ``binary_present``, ``installed_build`` and ``_activate``
    all run for real.

    Both values of ``CAMOUFOX_AUTO_UPDATE`` are required to activate. That flag buys the
    user out of network fetches, not out of running the build they pinned, and pointing
    camoufox at an already-installed local build never leaves the machine.
    """
    from camoufox_mcp.config import DEFAULT_BROWSER_VERSION

    config = _config(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE=auto_update)
    updater.write_update_stamp(config)
    assert updater.schedule_refresh(config) is None, "the 24h throttle must be closed here"

    installed = _pinned_install(data_dir, is_active=False)
    assert installed.version.full_string == DEFAULT_BROWSER_VERSION, (
        "the stand-in must carry the version the config pins, or it would never match"
    )
    activated = _only_install_is(monkeypatch, installed)

    await updater.ensure_browser_present(config)

    assert activated == [installed.relative_path]


async def test_an_already_active_pin_is_left_alone(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, forbid_downloads: None
) -> None:
    """Control for the test above: re-asserting the pin writes nothing when it holds.

    Startup runs this on every start, so an unconditional write would churn the shared
    camoufox config file for no gain, and would make the test above pass even if the
    ``is_active`` check were dropped.
    """
    config = _config(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    activated = _only_install_is(monkeypatch, _pinned_install(data_dir, is_active=True))

    await updater.ensure_browser_present(config)

    assert activated == []


async def test_an_explicit_binary_skips_activation(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``CAMOUFOX_BINARY`` wins outright, so the pin must not be re-asserted under it.

    The version pin is documented as ignored when a binary path is given. Activating a
    build the launch will not use would silently change which build every OTHER camoufox
    consumer on the machine gets.
    """
    binary = data_dir / "camoufox-bin"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("", encoding="utf-8")
    config = _config(
        data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true", CAMOUFOX_BINARY=str(binary)
    )
    activated = _only_install_is(monkeypatch, _pinned_install(data_dir, is_active=False))

    await updater.ensure_browser_present(config)

    assert activated == []


async def test_the_no_download_trap_can_actually_fire(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, forbid_downloads: None
) -> None:
    """Control for the test above: with the build absent, the trap does fire.

    Without this, a trap wired to a function nobody calls would make the no-download
    test unfalsifiable, which is exactly the failure mode being audited.
    """
    config = _config(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    monkeypatch.setattr(updater, "binary_present", lambda _config: False)

    with pytest.raises(updater.BrowserSetupError, match="download attempted"):
        await updater.ensure_browser_present(config)


async def test_unknown_pinned_build_fails_loudly(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that is neither installed nor installable is a hard, named error.

    With auto-update off there is nothing to fall back to, and silently launching
    some other build is exactly the drift the pin exists to stop.
    """
    config = _config(
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
