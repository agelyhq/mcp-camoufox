from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import paths, spawn
from camoufox_mcp.daemon.identity import DaemonIdentity, local_identity
from camoufox_mcp.daemon.proxy import build_proxy
from camoufox_mcp.daemon.socket_path import ensure_socket_dir
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health
from tests.daemon_harness import (
    ENDPOINT,
    IS_WINDOWS,
    Harness,
    advert_path,
    assert_hardened,
    control_client,
    daemon_session,
    reap,
    wait_gone,
)
from tests.helpers import tool_text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from camoufox_mcp.daemon.endpoint import DaemonEndpoint


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Isolated daemon for one test (see :mod:`tests.daemon_harness`)."""
    yield from daemon_session(monkeypatch)


def _write_stale_advert(cfg: ServerConfig) -> None:
    if IS_WINDOWS:
        paths.ensure_daemon_dir(cfg)
        paths.endpoint_path(cfg).write_text("not-valid-json", encoding="utf-8")
    else:
        ensure_socket_dir(cfg).write_bytes(b"stale")


async def test_two_proxies_share_one_daemon(daemon_env: Harness, flask_server: str) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy_a:
        await proxy_a.call_tool("navigate", {"profile": "alpha", "url": flask_server})

    # A brand-new proxy (fresh backend session) sees the session created by proxy A.
    async with Client(build_proxy(cfg, ENDPOINT)) as proxy_b:
        listing = tool_text(await proxy_b.call_tool("list_sessions", {}))
        assert "alpha" in listing

        await proxy_b.call_tool("navigate", {"profile": "beta", "url": flask_server})
        listing = tool_text(await proxy_b.call_tool("list_sessions", {}))
        assert "alpha" in listing
        assert "beta" in listing


def test_spawn_replaces_stale_advert(daemon_env: Harness) -> None:
    cfg = ServerConfig.from_env()
    # A leftover advert at the address from a crashed daemon.
    _write_stale_advert(cfg)

    ensure_daemon(cfg, ENDPOINT)

    health = probe_health(cfg, ENDPOINT)
    assert health is not None
    assert local_identity(cfg).matches(health)
    assert_hardened(cfg)


def test_idle_ttl_exits(daemon_env: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMOUFOX_DAEMON_TTL", "2")
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)

    health = probe_health(cfg, ENDPOINT)
    assert health is not None
    pid = int(health["pid"])

    assert wait_gone(cfg, deadline=15.0), "daemon did not idle-exit within its TTL"
    assert reap(cfg, pid), "idle daemon process did not actually terminate"
    assert not advert_path(cfg).exists(), "the exiting daemon left its advert behind"


def test_idle_mismatch_shuts_down_old_then_respawns(
    daemon_env: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    first = probe_health(cfg, ENDPOINT)
    assert first is not None
    old_pid = int(first["pid"])

    spawned: dict[str, bool] = {}

    # Must mirror spawn._spawn_locked exactly: the endpoint strategy became an
    # argument, and a stand-in still taking the old 2 raises TypeError inside
    # ensure_daemon instead of standing in for it.
    def _fake_spawn(
        config: ServerConfig, endpoint: DaemonEndpoint, identity: DaemonIdentity
    ) -> None:
        spawned["called"] = True

    monkeypatch.setattr(spawn, "local_identity", _mismatched_identity)
    monkeypatch.setattr(spawn, "_spawn_locked", _fake_spawn)

    ensure_daemon(cfg, ENDPOINT)

    assert spawned.get("called"), "mismatch path did not proceed to (re)spawn"
    assert probe_health(cfg, ENDPOINT) is None, "idle mismatched daemon was not shut down"
    assert reap(cfg, old_pid), "old mismatched daemon process did not terminate"


async def test_active_mismatch_is_reused_not_killed(
    daemon_env: Harness, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        await proxy.call_tool("navigate", {"profile": "live", "url": flask_server})

    before = probe_health(cfg, ENDPOINT)
    assert before is not None
    assert before["active_sessions"] == 1

    monkeypatch.setattr(spawn, "local_identity", _mismatched_identity)
    ensure_daemon(cfg, ENDPOINT)

    after = probe_health(cfg, ENDPOINT)
    assert after is not None
    assert after["started_at"] == before["started_at"]  # same process, never respawned
    assert after["active_sessions"] == 1


async def test_shutdown_refused_while_sessions_active(
    daemon_env: Harness, flask_server: str
) -> None:
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        await proxy.call_tool("navigate", {"profile": "busy", "url": flask_server})

    with control_client(cfg) as client:
        response = client.post("/shutdown")  # unforced
    assert response.status_code == 409
    assert probe_health(cfg, ENDPOINT) is not None


def _mismatched_identity(config: ServerConfig) -> DaemonIdentity:
    """Identity of a proxy running different code than the daemon it finds."""
    return DaemonIdentity(
        version="9.9.9-mismatch",
        code_path="/nowhere",
        data_dir=str(config.data_dir),
    )
