"""Stand-ins for the camoufox install list, and the traps that keep a start offline.

Shared by :mod:`tests.test_autoupdate` (the download branch) and
:mod:`tests.test_autoupdate_pin` (the pin and ``CAMOUFOX_BINARY``). Both drive
``updater.ensure_browser_present`` for real, so neither may reach the network or rewrite
the active install on the developer's own machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp import updater
from camoufox_mcp.config import ServerConfig
from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# The 3 entry points that can reach the network. Every "this start downloads nothing"
# test traps all 3, because trapping only the one it expects to be skipped would pass
# just as green if the call had moved to a sibling.
DOWNLOAD_ENTRY_POINTS = ("update_browser", "update_geoip", "install_build")


def config_for(data_dir: Path, monkeypatch: pytest.MonkeyPatch, **overrides: str) -> ServerConfig:
    """An isolated config, with ``overrides`` applied as full env var names."""
    isolate_camoufox_env(monkeypatch, data_dir, **overrides)
    return ServerConfig.from_env()


def forbid_download(*_args: object, **_kwargs: object) -> None:
    """Stand in for one download entry point, failing the test if it is ever called."""
    raise AssertionError("download attempted")


def forbid_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Booby-trap every path to the network, so a start that fetches anything fails.

    A plain call rather than a fixture: a test that traps only some of the 3 entry points
    (because reaching the branch under test requires one of them to run) then reads as a
    deliberate choice at the top of the body instead of as a missing fixture.
    """
    for name in DOWNLOAD_ENTRY_POINTS:
        monkeypatch.setattr(updater, name, forbid_download)


def pinned_install(data_dir: Path, *, is_active: bool) -> Any:
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


def only_install_is(monkeypatch: pytest.MonkeyPatch, installed: Any) -> list[str]:
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
