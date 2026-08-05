"""Shared fixture and process helpers for the daemon end-to-end tests.

Every daemon test spawns a real detached process, so teardown has to be pessimistic:
ask it to leave, then kill by pid, then reap. The helpers live here so several test
modules drive the same daemon lifecycle instead of each growing its own copy.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.endpoint import select_endpoint
from camoufox_mcp.daemon.socket_path import published_socket_path
from camoufox_mcp.daemon.spawn import probe_health
from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

IS_WINDOWS = os.name == "nt"

# The control-channel strategy the tests drive, built once like the daemon and the
# proxy build theirs. Every daemon helper takes it as an argument.
ENDPOINT = select_endpoint()


class Harness:
    """Holds the address-bearing config so teardown can always reach the daemon.

    ``track`` records daemons a test knows about beyond the one currently
    advertised, so an orphan left behind by a failing assertion is still killed.
    """

    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg
        self.pids: set[int] = set()

    def track(self, pid: int) -> None:
        self.pids.add(pid)


def daemon_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Body of the per-test ``daemon_env`` fixture: private data dir, headless, no update.

    A plain generator rather than a fixture, so each test module declares its own
    ``daemon_env`` instead of importing one (an imported fixture reads as a redefinition
    at every test signature that takes it).
    """
    data_dir = Path(tempfile.mkdtemp(prefix="cfxd-"))
    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_DAEMON_TTL="60")

    harness = Harness(ServerConfig.from_env())
    try:
        yield harness
    finally:
        force_teardown(harness)
        rmtree_retry(data_dir)


def advert_path(cfg: ServerConfig) -> Path:
    """Filesystem location of the daemon's address advert on this platform."""
    return paths.endpoint_path(cfg) if IS_WINDOWS else published_socket_path(cfg)


def control_client(cfg: ServerConfig) -> httpx.Client:
    conn = ENDPOINT.resolve(cfg)
    assert conn is not None, "daemon advertised no address"
    return ENDPOINT.sync_client(conn)


def rmtree_retry(path: Path, deadline: float = 8.0) -> None:
    """Remove the data dir, retrying while Camoufox flushes its profile on exit.

    Firefox keeps writing the profile (sessionstore, telemetry, startupCache) for a
    second or two after Playwright's ``close()`` returns, so a single rmtree can race
    that flush and leave a partial dir behind.
    """
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        shutil.rmtree(path, ignore_errors=True)
        # Let any lingering Firefox content process finish flushing, then confirm
        # the dir stays gone — an immediate re-check would miss a late rewrite.
        time.sleep(0.5)
        if not path.exists():
            return
    shutil.rmtree(path, ignore_errors=True)


def force_teardown(harness: Harness) -> None:
    """Force-shut the advertised daemon, then hard-kill every pid the test saw."""
    cfg = harness.cfg
    health = probe_health(cfg, ENDPOINT)
    if health is not None:
        if health.get("pid"):
            harness.track(int(health["pid"]))
        with contextlib.suppress(httpx.HTTPError, OSError), control_client(cfg) as client:
            client.post("/shutdown", params={"force": "true"})
        wait_gone(cfg)
    for pid in harness.pids:
        if alive(pid):
            hard_kill(pid)
        reap(cfg, pid)
    with contextlib.suppress(OSError):
        advert_path(cfg).unlink()


def alive(pid: int) -> bool:
    if IS_WINDOWS:
        return True  # No cheap liveness check; the kill below is harmless either way.
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def hard_kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        # Windows has no SIGKILL; os.kill with SIGTERM maps to TerminateProcess.
        os.kill(pid, signal.SIGTERM if IS_WINDOWS else signal.SIGKILL)


def wait_gone(cfg: ServerConfig, deadline: float = 15.0) -> bool:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if probe_health(cfg, ENDPOINT) is None:
            return True
        time.sleep(0.1)
    return probe_health(cfg, ENDPOINT) is None


def wait_advert_gone(cfg: ServerConfig, deadline: float = 10.0) -> bool:
    """Wait for the advert to disappear, rather than demanding it already has.

    A daemon stops answering, exits, and unlinks its advert, in that order. On a 2-core
    runner those 3 can land whole seconds apart, so asserting the file is gone the instant
    the process is reaped tests the scheduler, not the cleanup. The condition asserted is
    unchanged: the advert must go. Only the "immediately" is dropped.
    """
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if not advert_path(cfg).exists():
            return True
        time.sleep(0.1)
    return not advert_path(cfg).exists()


def reap(cfg: ServerConfig, pid: int, deadline: float = 5.0) -> bool:
    """Confirm a spawned daemon has actually terminated.

    On POSIX the daemon is a child of this process, so an unreaped exit lingers as a
    zombie that still answers signal 0; ``waitpid`` reaps it. Windows has no zombies
    and no ``waitpid`` for a pid, so a vanished health endpoint is proof of exit.
    """
    if IS_WINDOWS:
        return wait_gone(cfg, deadline)
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if reaped == pid:
            return True
        time.sleep(0.05)
    return False


def assert_hardened(cfg: ServerConfig) -> None:
    """The freshly bound control channel must be reachable only by its owner."""
    if IS_WINDOWS:
        # No Unix socket file mode on Windows; the bearer token is the boundary, so
        # an unauthenticated request must be refused.
        conn = ENDPOINT.resolve(cfg)
        assert conn is not None
        with httpx.Client(base_url=conn.base_url, timeout=2.0) as raw:
            assert raw.get("/health").status_code == 401
        return
    # The daemon tightens uvicorn's default 0o666 socket mode shortly after bind.
    socket_path = published_socket_path(cfg)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if (socket_path.stat().st_mode & 0o777) == 0o600:
            break
        time.sleep(0.05)
    assert (socket_path.stat().st_mode & 0o777) == 0o600
