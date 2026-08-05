"""Where the POSIX control socket lives, and what happens when it cannot fit.

``sun_path`` caps an AF_UNIX address near 108 bytes, so the socket cannot live under
an arbitrarily deep data dir. These tests drive the real spawn path with a data dir
long enough to have made the old location unbindable.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.errors import SocketPathTooLongError
from camoufox_mcp.daemon.identity import local_identity
from camoufox_mcp.daemon.socket_path import (
    MAX_SOCKET_PATH_BYTES,
    daemon_socket_path,
    published_socket_path,
)
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health
from tests.daemon_harness import (
    ENDPOINT,
    IS_WINDOWS,
    Harness,
    assert_hardened,
    daemon_session,
    rmtree_retry,
)
from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(
    IS_WINDOWS, reason="Windows binds a loopback port; sun_path does not apply"
)


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Isolated daemon for one test (see :mod:`tests.daemon_harness`)."""
    yield from daemon_session(monkeypatch)


# Long enough that "<data_dir>/daemon/daemon.sock" cannot fit in sun_path.
_LONG_TAIL = ("deeply-nested-workspace-" * 3, "checkout-" * 5)


def _long_data_dir(root: Path) -> Path:
    return root.joinpath(*_LONG_TAIL)


@pytest.fixture
def long_daemon_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Harness]:
    """A daemon whose data dir is too deep for ``sun_path`` to hold its socket."""
    yield from daemon_session(monkeypatch, _long_data_dir(tmp_path))


@pytest.fixture
def runtime_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A throwaway XDG_RUNTIME_DIR, removed however the test ends."""
    directory = Path(tempfile.mkdtemp(prefix="cfxr-"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(directory))
    try:
        yield directory
    finally:
        rmtree_retry(directory)


def test_long_data_dir_still_starts_the_daemon(long_daemon_env: Harness, runtime_dir: Path) -> None:
    """A data dir too deep for sun_path must not stop the daemon from binding."""
    cfg = ServerConfig.from_env()
    assert len(str(paths.socket_path(cfg))) > MAX_SOCKET_PATH_BYTES, "data dir not long enough"

    ensure_daemon(cfg, ENDPOINT)

    health = probe_health(cfg, ENDPOINT)
    assert health is not None
    assert local_identity(cfg).matches(health)
    assert daemon_socket_path(cfg).is_relative_to(runtime_dir)
    assert_hardened(cfg)


def test_socket_over_the_limit_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no runtime dir to fall back on, bind names the limit instead of raising OSError."""
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    data_dir = _long_data_dir(tmp_path)
    isolate_camoufox_env(monkeypatch, data_dir)
    cfg = ServerConfig.from_env()

    with pytest.raises(SocketPathTooLongError) as excinfo:
        ENDPOINT.bind(cfg)

    message = str(excinfo.value)
    assert str(MAX_SOCKET_PATH_BYTES) in message
    assert str(paths.socket_path(cfg)) in message


def test_socket_falls_back_to_the_data_dir_without_a_runtime_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    isolate_camoufox_env(monkeypatch, tmp_path / "data")
    cfg = ServerConfig.from_env()

    assert daemon_socket_path(cfg) == paths.socket_path(cfg)


def test_a_proxy_without_a_runtime_dir_finds_the_running_daemon(
    daemon_env: Harness, runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Processes that disagree about XDG_RUNTIME_DIR must still share one daemon."""
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    started = probe_health(cfg, ENDPOINT)
    assert started is not None
    daemon_env.track(int(started["pid"]))

    # A second process, same data dir, no runtime dir in its environment: it
    # derives its own config, which is where the runtime dir is now read.
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    other = ServerConfig.from_env()
    assert daemon_socket_path(other) != published_socket_path(other)

    found = probe_health(other, ENDPOINT)
    assert found is not None, "the pointer in the data dir did not lead to the daemon"
    ensure_daemon(other, ENDPOINT)
    assert probe_health(other, ENDPOINT)["pid"] == started["pid"], "a second daemon was spawned"


def test_a_second_data_dir_gets_its_own_control_channel(
    daemon_env: Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two data dirs must never meet on one socket now that the path left the data dir."""
    cfg_a = ServerConfig.from_env()
    ensure_daemon(cfg_a, ENDPOINT)
    health_a = probe_health(cfg_a, ENDPOINT)
    assert health_a is not None
    daemon_env.track(int(health_a["pid"]))

    isolate_camoufox_env(monkeypatch, tmp_path / "other-data", CAMOUFOX_DAEMON_TTL="60")
    cfg_b = ServerConfig.from_env()

    assert daemon_socket_path(cfg_b) != daemon_socket_path(cfg_a)
    assert ENDPOINT.resolve(cfg_b) is None, "a foreign data dir found daemon A's channel"
    assert not local_identity(cfg_b).matches(health_a), "identity ignored the data dir"
