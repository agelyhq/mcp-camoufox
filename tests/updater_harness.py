"""Stand-ins for the camoufox install list, and the fetchers that keep a start offline.

Shared by :mod:`tests.test_autoupdate` (the download branch) and
:mod:`tests.test_autoupdate_pin` (the pin and ``CAMOUFOX_BINARY``). Both drive
``updater.ensure_browser_present`` for real, so neither may reach the network or rewrite
the active install on the developer's own machine.

Every fetch the updater performs goes through the ``fetch`` callable its public entry
points take, the child-process spawner by default. A test hands in one of the fetchers
here instead: nothing is monkeypatched to keep a start offline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.config import ServerConfig
from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def config_for(data_dir: Path, monkeypatch: pytest.MonkeyPatch, **overrides: str) -> ServerConfig:
    """An isolated config, with ``overrides`` applied as full env var names."""
    isolate_camoufox_env(monkeypatch, data_dir, **overrides)
    return ServerConfig.from_env()


async def forbid_fetch(_config: ServerConfig, asset: str) -> None:
    """Stand in for the fetch child, failing the test if any asset is ever fetched."""
    raise AssertionError(f"download attempted: {asset}")


class RecordingFetcher:
    """A fetcher that records the assets it was asked for, in order.

    ``failing`` names the assets whose fetch raises, the way the child does on a refused
    network; ``on_browser`` runs when the browser is fetched, so a test can make the
    install list reflect what the child would have put on disk.
    """

    def __init__(self, *, failing: frozenset[str] = frozenset(), on_browser: Any = None) -> None:
        self.assets: list[str] = []
        self.versions: list[str | None] = []
        self._failing = failing
        self._on_browser = on_browser

    async def __call__(self, config: ServerConfig, asset: str) -> None:
        self.assets.append(asset)
        self.versions.append(config.browser_version)
        if asset in self._failing:
            raise RuntimeError(f"{asset} fetch refused")
        if asset == "browser" and self._on_browser is not None:
            self._on_browser()


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

    ``None`` means nothing is installed. Only the 2 upstream boundary functions are
    replaced, so ``binary_present``, ``installed_build`` and ``activate`` all run for
    real, and no test rewrites the shared camoufox config on the developer's machine.
    """
    from camoufox import multiversion

    activated: list[str] = []
    make_installed(monkeypatch, installed)
    monkeypatch.setattr(multiversion, "set_active", activated.append)
    return activated


def make_installed(monkeypatch: pytest.MonkeyPatch, installed: Any) -> None:
    """Make the install list report ``installed`` (``None``: nothing) from now on.

    What a fetch child leaves behind, seen from the parent: only the listing changes,
    so an ``activated`` list handed out earlier keeps recording.
    """
    from camoufox import multiversion

    listing = [] if installed is None else [installed]
    monkeypatch.setattr(multiversion, "list_installed", lambda: listing)
