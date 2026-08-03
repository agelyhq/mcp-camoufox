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
import pytest
from fastmcp import Client

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import spawn
from camoufox_mcp.daemon.endpoint import ENDPOINT
from camoufox_mcp.daemon.identity import health_matches_identity, local_identity
from camoufox_mcp.daemon.proxy import build_proxy
from camoufox_mcp.daemon.spawn import _probe_health, ensure_daemon
from tests.helpers import isolate_camoufox_env, tool_text

if TYPE_CHECKING:
    from collections.abc import Iterator

IS_WINDOWS = os.name == "nt"


class _Harness:
    """Holds the address-bearing config so teardown can always reach the daemon."""

    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Harness]:
    """Isolated daemon per test: short data dir, headless, no auto-update.

    Teardown force-shuts the daemon, then hard-kills by pid as a last resort so a
    detached process is never leaked even when the test body fails.
    """
    # A short path keeps the POSIX UDS under the ~108-char AF_UNIX limit; Windows
    # uses a loopback socket, so its temp dir length is irrelevant.
    tmp_root = None if IS_WINDOWS else "/tmp"
    data_dir = Path(tempfile.mkdtemp(prefix="cfxd-", dir=tmp_root))
    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_DAEMON_TTL="60")

    harness = _Harness(ServerConfig.from_env())
    try:
        yield harness
    finally:
        _force_teardown(harness.cfg)
        _rmtree_retry(data_dir)


def _client(cfg: ServerConfig) -> httpx.Client:
    conn = ENDPOINT.resolve(cfg)
    assert conn is not None, "daemon advertised no address"
    return ENDPOINT.sync_client(conn)


def _rmtree_retry(path: Path, deadline: float = 8.0) -> None:
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


def _force_teardown(cfg: ServerConfig) -> None:
    health = _probe_health(cfg)
    if health is None:
        return
    pid = int(health["pid"]) if health.get("pid") else None
    with contextlib.suppress(httpx.HTTPError, OSError), _client(cfg) as client:
        client.post("/shutdown", params={"force": "true"})
    gone = _wait_gone(cfg)
    if pid is not None:
        if not gone:
            _hard_kill(pid)
        _reap(cfg, pid)


def _hard_kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        # Windows has no SIGKILL; os.kill with SIGTERM maps to TerminateProcess.
        os.kill(pid, signal.SIGTERM if IS_WINDOWS else signal.SIGKILL)


def _wait_gone(cfg: ServerConfig, deadline: float = 15.0) -> bool:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if _probe_health(cfg) is None:
            return True
        time.sleep(0.1)
    return _probe_health(cfg) is None


def _reap(cfg: ServerConfig, pid: int, deadline: float = 5.0) -> bool:
    """Confirm a spawned daemon has actually terminated.

    On POSIX the daemon is a child of this process, so an unreaped exit lingers as a
    zombie that still answers signal 0; ``waitpid`` reaps it. Windows has no zombies
    and no ``waitpid`` for a pid, so a vanished health endpoint is proof of exit.
    """
    if IS_WINDOWS:
        return _wait_gone(cfg, deadline)
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


def _assert_hardened(cfg: ServerConfig) -> None:
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
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if (cfg.daemon_socket_path.stat().st_mode & 0o777) == 0o600:
            break
        time.sleep(0.05)
    assert (cfg.daemon_socket_path.stat().st_mode & 0o777) == 0o600


def _write_stale_advert(cfg: ServerConfig) -> None:
    cfg.ensure_daemon_dir()
    if IS_WINDOWS:
        cfg.daemon_endpoint_path.write_text("not-valid-json", encoding="utf-8")
    else:
        cfg.daemon_socket_path.write_bytes(b"stale")


async def test_two_proxies_share_one_daemon(daemon_env: _Harness, flask_server: str) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg)

    async with Client(build_proxy(cfg)) as proxy_a:
        await proxy_a.call_tool("navigate", {"profile": "alpha", "url": flask_server})

    # A brand-new proxy (fresh backend session) sees the session created by proxy A.
    async with Client(build_proxy(cfg)) as proxy_b:
        listing = tool_text(await proxy_b.call_tool("list_sessions", {}))
        assert "alpha" in listing

        await proxy_b.call_tool("navigate", {"profile": "beta", "url": flask_server})
        listing = tool_text(await proxy_b.call_tool("list_sessions", {}))
        assert "alpha" in listing
        assert "beta" in listing


def test_spawn_replaces_stale_advert(daemon_env: _Harness) -> None:
    cfg = ServerConfig.from_env()
    # A leftover advert at the address from a crashed daemon.
    _write_stale_advert(cfg)

    ensure_daemon(cfg)

    health = _probe_health(cfg)
    assert health is not None
    assert health_matches_identity(health, local_identity())
    _assert_hardened(cfg)


def test_idle_ttl_exits(daemon_env: _Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMOUFOX_DAEMON_TTL", "2")
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg)

    health = _probe_health(cfg)
    assert health is not None
    pid = int(health["pid"])

    assert _wait_gone(cfg, deadline=15.0), "daemon did not idle-exit within its TTL"
    assert _reap(cfg, pid), "idle daemon process did not actually terminate"


def test_idle_mismatch_shuts_down_old_then_respawns(
    daemon_env: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg)
    first = _probe_health(cfg)
    assert first is not None
    old_pid = int(first["pid"])

    spawned: dict[str, bool] = {}

    def _fake_spawn(config: ServerConfig, identity: tuple[str, str]) -> None:
        spawned["called"] = True

    monkeypatch.setattr(spawn, "local_identity", lambda: ("9.9.9-mismatch", "/nowhere"))
    monkeypatch.setattr(spawn, "_spawn_locked", _fake_spawn)

    ensure_daemon(cfg)

    assert spawned.get("called"), "mismatch path did not proceed to (re)spawn"
    assert _probe_health(cfg) is None, "idle mismatched daemon was not shut down"
    assert _reap(cfg, old_pid), "old mismatched daemon process did not terminate"


async def test_active_mismatch_is_reused_not_killed(
    daemon_env: _Harness, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg)

    async with Client(build_proxy(cfg)) as proxy:
        await proxy.call_tool("navigate", {"profile": "live", "url": flask_server})

    before = _probe_health(cfg)
    assert before is not None
    assert before["active_sessions"] == 1

    monkeypatch.setattr(spawn, "local_identity", lambda: ("9.9.9-mismatch", "/nowhere"))
    ensure_daemon(cfg)

    after = _probe_health(cfg)
    assert after is not None
    assert after["started_at"] == before["started_at"]  # same process, never respawned
    assert after["active_sessions"] == 1


async def test_shutdown_refused_while_sessions_active(
    daemon_env: _Harness, flask_server: str
) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg)

    async with Client(build_proxy(cfg)) as proxy:
        await proxy.call_tool("navigate", {"profile": "busy", "url": flask_server})

    with _client(cfg) as client:
        response = client.post("/shutdown")  # unforced
    assert response.status_code == 409
    assert _probe_health(cfg) is not None
