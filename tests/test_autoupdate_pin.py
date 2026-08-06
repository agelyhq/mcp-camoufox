"""What startup does with the build pin, and what ``CAMOUFOX_BINARY`` does to it.

Camoufox derives the spoofed Firefox version and its asset paths from the ACTIVE install
rather than from the binary a launch selects, so activation is not cosmetic. It is also
machine-wide, which is why every test here proves what it did or did not activate. The
download branch and the 24h throttle live in :mod:`tests.test_autoupdate`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from camoufox_mcp import updater
from tests.updater_harness import (
    config_for,
    forbid_download,
    forbid_downloads,
    only_install_is,
    pinned_install,
)

if TYPE_CHECKING:
    from pathlib import Path


async def test_pinned_build_present_needs_no_download(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pin means "do not move": startup must never reach for the network.

    The whole body used to be setup. Booby-trapping the download and then calling the
    function asserts nothing on its own: a gutted ``ensure_browser_present`` that did
    no work at all would pass just as green, and so would a machine where the pinned
    build is missing but some other early return fires. Two things make it real. The
    precondition pins WHY the download is skipped, and
    ``test_the_no_download_trap_can_actually_fire`` proves the traps can fire at all.
    """
    from camoufox import multiversion

    from camoufox_mcp.config import DEFAULT_BROWSER_VERSION

    forbid_downloads(monkeypatch)
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")

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


async def test_the_no_download_trap_can_actually_fire(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the test above: with the build absent, the trap does fire.

    Without this, a trap wired to a function nobody calls would make the no-download
    test unfalsifiable, which is exactly the failure mode being audited.
    """
    forbid_downloads(monkeypatch)
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    monkeypatch.setattr(updater, "binary_present", lambda _config: False)

    with pytest.raises(updater.BrowserSetupError, match="download attempted"):
        await updater.ensure_browser_present(config)


@pytest.mark.parametrize("auto_update", ["true", "false"])
async def test_pinned_build_is_activated_on_a_throttled_start(
    auto_update: str, data_dir: Path, monkeypatch: pytest.MonkeyPatch
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

    forbid_downloads(monkeypatch)
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE=auto_update)
    updater.write_update_stamp(config)
    assert updater.schedule_refresh(config) is None, "the 24h throttle must be closed here"

    installed = pinned_install(data_dir, is_active=False)
    assert installed.version.full_string == DEFAULT_BROWSER_VERSION, (
        "the stand-in must carry the version the config pins, or it would never match"
    )
    activated = only_install_is(monkeypatch, installed)

    await updater.ensure_browser_present(config)

    assert activated == [installed.relative_path]


async def test_an_already_active_pin_is_left_alone(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the test above: re-asserting the pin writes nothing when it holds.

    Startup runs this on every start, so an unconditional write would churn the shared
    camoufox config file for no gain, and would make the test above pass even if the
    ``is_active`` check were dropped.
    """
    forbid_downloads(monkeypatch)
    config = config_for(data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true")
    activated = only_install_is(monkeypatch, pinned_install(data_dir, is_active=True))

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
    config = config_for(
        data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true", CAMOUFOX_BINARY=str(binary)
    )
    activated = only_install_is(monkeypatch, pinned_install(data_dir, is_active=False))

    await updater.ensure_browser_present(config)

    assert activated == []


async def test_a_missing_camoufox_binary_is_named_and_activates_nothing(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo'd ``CAMOUFOX_BINARY`` is a named error, not a machine-wide activation.

    ``binary_present`` reports False for a path that is not there, which routed the start
    into the cold-install branch: it fetched the pinned build if absent and ended in
    ``set_active``, changing which build every other camoufox consumer on this machine
    gets. Camoufox then gives ``executable_path`` precedence over that build, so the
    launch failed anyway on the missing executable, with an error naming no path. The test
    above covers only a binary that DOES exist, so the guard was bypassed by the one input
    that matters.

    Teeth: the pinned build is present-but-inactive here, so the old path really did have
    something to activate, and the fetch and the GeoIP download are trapped so the old
    path cannot instead pass by failing at the network.
    """
    missing = data_dir / "typo" / "camoufox-bin"
    config = config_for(
        data_dir, monkeypatch, CAMOUFOX_AUTO_UPDATE="true", CAMOUFOX_BINARY=str(missing)
    )
    activated = only_install_is(monkeypatch, pinned_install(data_dir, is_active=False))
    monkeypatch.setattr(updater, "install_build", forbid_download)
    monkeypatch.setattr(updater, "update_geoip", forbid_download)

    with pytest.raises(updater.BrowserSetupError) as raised:
        await updater.ensure_browser_present(config)

    message = str(raised.value)
    assert str(missing) in message, "the error must name the path that is wrong"
    assert "CAMOUFOX_BINARY" in message, "and the variable that carried it"
    assert activated == []
