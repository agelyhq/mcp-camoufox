"""Withdrawing an advert: a daemon removes its own publication and nothing else.

The end-to-end daemon tests prove the advert goes when a real daemon exits. What they
cannot stage is 2 daemons publishing at 1 address, which is the case the proof exists
for: an advert withdrawn by anyone but its publisher strands a live daemon's browsers.

Both control-channel strategies are driven here, on this platform. The Windows one binds
a loopback socket and writes a file, so its whole advert contract runs on Linux, where
nothing else in the suite so much as imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.endpoint_loopback import LoopbackEndpoint
from camoufox_mcp.daemon.endpoint_unix import UnixSocketEndpoint
from camoufox_mcp.daemon.socket_path import address_pointer_path
from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.daemon.endpoint import DaemonEndpoint

_STRATEGIES = ("unix", "loopback")


@pytest.fixture
def cfg(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> ServerConfig:
    """An isolated config with the 0o700 daemon dir a bind expects to find."""
    isolate_camoufox_env(monkeypatch, data_dir)
    config = ServerConfig.from_env()
    paths.ensure_daemon_dir(config)
    return config


def _strategy(config: ServerConfig, name: str) -> tuple[DaemonEndpoint, Path]:
    """The endpoint under test and the file its ``bind`` publishes the address in."""
    if name == "unix":
        return UnixSocketEndpoint(), address_pointer_path(config)
    return LoopbackEndpoint(), paths.endpoint_path(config)


@pytest.mark.parametrize("name", _STRATEGIES)
def test_bind_hands_back_a_proof_that_withdraws_that_publication(
    cfg: ServerConfig, name: str
) -> None:
    endpoint, advert = _strategy(cfg, name)

    proof = endpoint.bind(cfg).advert_id

    assert proof is not None, "bind published an advert without naming it"
    assert advert.exists()
    assert endpoint.cleanup_if_owned(cfg, proof) is True
    assert not advert.exists()


@pytest.mark.parametrize("name", _STRATEGIES)
def test_a_later_publication_makes_the_earlier_proof_worthless(
    cfg: ServerConfig, name: str
) -> None:
    """The second daemon owns the address; the first must not be able to strand it."""
    endpoint, advert = _strategy(cfg, name)

    first = endpoint.bind(cfg).advert_id
    second = endpoint.bind(cfg).advert_id

    assert first is not None
    assert second != first, "2 publications at 1 address were indistinguishable"
    assert endpoint.cleanup_if_owned(cfg, first) is False
    assert advert.exists(), "an exiting daemon withdrew the advert of the one that replaced it"
    assert endpoint.cleanup_if_owned(cfg, second) is True
    assert not advert.exists()
