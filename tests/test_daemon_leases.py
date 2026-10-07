"""A connected proxy keeps its daemon alive however long its user is silent, and the
daemon still goes once the last proxy has left, cleanly or not."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon.leases import MAX_LEASE_TTL_S
from camoufox_mcp.daemon.proxy import build_proxy
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health
from tests.daemon_harness import (
    ENDPOINT,
    LEASE_INTERVAL_S,
    Harness,
    alive,
    control_client,
    daemon_diagnostics,
    daemon_session,
    hard_kill,
    lease_count,
    reap,
    wait_advert_gone,
    wait_gone,
    wait_leases,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_TTL_S = 2
_LEASE_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Isolated daemon for one test, idling out after ``_TTL_S`` seconds."""
    for harness in daemon_session(monkeypatch):
        monkeypatch.setenv("CAMOUFOX_DAEMON_TTL", str(_TTL_S))
        yield harness


def _start(cfg: ServerConfig, harness: Harness) -> int:
    ensure_daemon(cfg, ENDPOINT)
    health = probe_health(cfg, ENDPOINT)
    assert health is not None
    pid = int(health["pid"])
    harness.track(pid)
    return pid


def _holds_for(cfg: ServerConfig, pid: int, seconds: float) -> None:
    """Assert the same daemon answers throughout ``seconds``: the claim IS a duration.

    Blocking, so it runs off the event loop: the in-process proxy's heartbeat must keep
    renewing while it watches.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        health = probe_health(cfg, ENDPOINT)
        assert health is not None, daemon_diagnostics(cfg, "the leased daemon exited")
        assert int(health["pid"]) == pid, "the daemon was replaced"
        time.sleep(0.2)


def _assert_exits(cfg: ServerConfig, pid: int) -> None:
    assert wait_gone(cfg, deadline=15.0), daemon_diagnostics(cfg, "daemon outlived its TTL")
    assert reap(cfg, pid), daemon_diagnostics(cfg, "idle daemon process did not terminate")
    assert wait_advert_gone(cfg), daemon_diagnostics(cfg, "the daemon left its advert")


async def test_a_leased_daemon_outlives_its_ttl(daemon_env: Harness) -> None:
    cfg = ServerConfig.from_env()
    pid = _start(cfg, daemon_env)

    async with Client(build_proxy(cfg, ENDPOINT)):
        assert lease_count(cfg) == 1
        await asyncio.to_thread(_holds_for, cfg, pid, 3 * _TTL_S + 1)

    # Released on the way out, not left to expire.
    assert lease_count(cfg) == 0
    _assert_exits(cfg, pid)


async def test_daemon_exits_ttl_after_the_last_of_two_leases(daemon_env: Harness) -> None:
    cfg = ServerConfig.from_env()
    pid = _start(cfg, daemon_env)

    async with Client(build_proxy(cfg, ENDPOINT)):
        async with Client(build_proxy(cfg, ENDPOINT)):
            assert lease_count(cfg) == 2
        assert lease_count(cfg) == 1
        await asyncio.to_thread(_holds_for, cfg, pid, 2 * _TTL_S + 1)

    _assert_exits(cfg, pid)


def test_a_killed_proxy_lease_expires(daemon_env: Harness) -> None:
    """A proxy killed outright never releases: its lease must lapse on its own."""
    cfg = ServerConfig.from_env()
    pid = _start(cfg, daemon_env)
    env = {**cfg.child_env(), "CAMOUFOX_DAEMON": "true"}
    proxy = subprocess.Popen(
        [sys.executable, "-c", "from camoufox_mcp.server import main; main()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        assert wait_leases(cfg, 1, deadline=30.0), daemon_diagnostics(cfg, "no lease taken")
        hard_kill(proxy.pid)
        proxy.wait(timeout=10)
        assert wait_leases(cfg, 0, deadline=3 * LEASE_INTERVAL_S + 5), daemon_diagnostics(
            cfg, "the dead proxy's lease never expired"
        )
        assert alive(pid)
        _assert_exits(cfg, pid)
    finally:
        if proxy.poll() is None:
            proxy.kill()
            proxy.wait(timeout=10)
        if proxy.stdin is not None:
            proxy.stdin.close()


def test_lease_rejects_malformed_and_clamps_ttl(daemon_env: Harness) -> None:
    cfg = ServerConfig.from_env()
    _start(cfg, daemon_env)

    with control_client(cfg) as client:
        assert client.post("/lease", json={"id": "nope", "ttl_s": 5}).status_code == 400
        assert client.post("/lease", json={"id": _LEASE_ID, "ttl_s": "5"}).status_code == 400
        assert client.post("/lease", json={"id": _LEASE_ID, "ttl_s": -1}).status_code == 400
        assert client.post("/lease", content=b"{").status_code == 400
        assert client.delete("/lease/NOT-HEX").status_code == 400

        granted = client.post("/lease", json={"id": _LEASE_ID, "ttl_s": 10_000})
        assert granted.status_code == 200
        body = granted.json()
        assert body["ttl_s"] == MAX_LEASE_TTL_S
        health = probe_health(cfg, ENDPOINT)
        assert health is not None
        assert (body["pid"], body["started_at"]) == (health["pid"], health["started_at"])
        assert health["leases"] == 1

        assert client.delete(f"/lease/{_LEASE_ID}").json() == {"released": True}
        assert client.delete(f"/lease/{_LEASE_ID}").json() == {"released": False}
    assert lease_count(cfg) == 0
