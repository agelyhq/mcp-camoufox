"""A daemon replaced behind a connected proxy must cost that proxy one call, not the rest
of its conversation, and must be reported exactly once.

The daemon is stateless over HTTP, so nothing fails on its own after a replacement: the
proxy has to notice the new daemon through its lease and say so.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import recovery
from camoufox_mcp.daemon.endpoint import mcp_url
from camoufox_mcp.daemon.proxy import build_proxy
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health
from tests.daemon_calls import session_registered, verdict_within
from tests.daemon_harness import (
    ENDPOINT,
    Harness,
    control_client,
    daemon_diagnostics,
    daemon_session,
    hard_kill,
    wait_gone,
    wait_leases,
)
from tests.helpers import tool_text

if TYPE_CHECKING:
    from collections.abc import Iterator

_MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Isolated daemon for one test (see :mod:`tests.daemon_harness`)."""
    yield from daemon_session(monkeypatch)


def _replace_daemon(cfg: ServerConfig, harness: Harness, old_pid: int) -> int:
    """Kill the daemon and do what another proxy starting up does: spawn a new one."""
    hard_kill(old_pid)
    assert wait_gone(cfg), daemon_diagnostics(cfg, "the daemon survived SIGKILL")
    ensure_daemon(cfg, ENDPOINT)
    replacement = probe_health(cfg, ENDPOINT)
    assert replacement is not None, "no replacement daemon came up"
    new_pid = int(replacement["pid"])
    assert new_pid != old_pid
    harness.track(new_pid)
    return new_pid


def _running_daemon(cfg: ServerConfig, harness: Harness) -> int:
    ensure_daemon(cfg, ENDPOINT)
    health = probe_health(cfg, ENDPOINT)
    assert health is not None
    pid = int(health["pid"])
    harness.track(pid)
    return pid


async def test_daemon_respawned_by_another_proxy_is_reported_once_then_works(
    daemon_env: Harness,
) -> None:
    """Proxy A idles while its daemon is replaced: 1 call reports it, the rest work."""
    cfg = ServerConfig.from_env()
    old_pid = _running_daemon(cfg, daemon_env)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        tool_text(await proxy.call_tool("list_sessions", {}))
        new_pid = await asyncio.to_thread(_replace_daemon, cfg, daemon_env, old_pid)

        with pytest.raises(Exception) as excinfo:
            await proxy.call_tool("list_sessions", {})
        assert str(excinfo.value) == recovery.RESTARTED_MESSAGE

        for _ in range(3):
            listing = tool_text(await proxy.call_tool("list_sessions", {}))
            assert "No active sessions" in listing

        after = probe_health(cfg, ENDPOINT)
        assert after is not None
        assert int(after["pid"]) == new_pid, "the proxy spawned a second replacement"


async def test_replacement_seen_by_the_heartbeat_reports_once_under_concurrency(
    daemon_env: Harness,
) -> None:
    """Concurrent calls after a replacement the heartbeat already saw: 1 fails, the rest pass."""
    cfg = ServerConfig.from_env()
    old_pid = _running_daemon(cfg, daemon_env)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        tool_text(await proxy.call_tool("list_sessions", {}))
        await asyncio.to_thread(_replace_daemon, cfg, daemon_env, old_pid)
        # The new daemon holds a lease only once this proxy's heartbeat renewed on it,
        # which is the renewal that saw the new instance: the notice is now pending.
        assert await asyncio.to_thread(wait_leases, cfg, 1), daemon_diagnostics(
            cfg, "the heartbeat never renewed on the replacement"
        )

        outcomes = await asyncio.gather(
            *(proxy.call_tool("list_sessions", {}) for _ in range(3)),
            return_exceptions=True,
        )

    failures = [str(o) for o in outcomes if isinstance(o, BaseException)]
    assert failures == [recovery.RESTARTED_MESSAGE], outcomes
    successes = [o for o in outcomes if not isinstance(o, BaseException)]
    assert all("No active sessions" in tool_text(o) for o in successes)


async def test_a_list_request_never_swallows_the_restart_notice(daemon_env: Harness) -> None:
    """The client lists on its own and never shows the model a list error: the notice
    must survive a list request and reach the next tool call."""
    cfg = ServerConfig.from_env()
    old_pid = _running_daemon(cfg, daemon_env)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        tool_text(await proxy.call_tool("list_sessions", {}))
        await asyncio.to_thread(_replace_daemon, cfg, daemon_env, old_pid)
        assert await asyncio.to_thread(wait_leases, cfg, 1), daemon_diagnostics(
            cfg, "the heartbeat never renewed on the replacement"
        )

        assert any(tool.name == "list_sessions" for tool in await proxy.list_tools())
        await proxy.list_resources()
        with pytest.raises(Exception) as excinfo:
            await proxy.call_tool("list_sessions", {})
        assert str(excinfo.value) == recovery.RESTARTED_MESSAGE
        assert "No active sessions" in tool_text(await proxy.call_tool("list_sessions", {}))


async def test_a_daemon_gone_before_the_handshake_is_replaced_silently(
    daemon_env: Harness,
) -> None:
    """A conversation that has not started has no browser to lose: its initialize
    respawns the daemon without an error, and no later call reports a restart."""
    cfg = ServerConfig.from_env()
    old_pid = _running_daemon(cfg, daemon_env)
    server = build_proxy(cfg, ENDPOINT)  # what run_proxy builds after ensure_daemon
    hard_kill(old_pid)
    assert await asyncio.to_thread(wait_gone, cfg), daemon_diagnostics(
        cfg, "the daemon survived SIGKILL"
    )

    async with Client(server) as proxy:
        health = probe_health(cfg, ENDPOINT)
        assert health is not None, "initialize did not respawn the daemon"
        daemon_env.track(int(health["pid"]))
        for _ in range(2):
            listing = tool_text(await proxy.call_tool("list_sessions", {}))
            assert "No active sessions" in listing


def test_the_daemon_is_stateless(daemon_env: Harness) -> None:
    """No session id is ever issued, and a request with none is served."""
    cfg = ServerConfig.from_env()
    _running_daemon(cfg, daemon_env)
    path = mcp_url().removeprefix("http://camoufox-daemon")
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "tests.test_daemon_replaced", "version": "0"},
        },
    }
    tools_list = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

    with control_client(cfg) as client:
        opened = client.post(path, json=initialize, headers=_MCP_HEADERS)
        listed = client.post(path, json=tools_list, headers=_MCP_HEADERS)

    assert opened.status_code == 200, opened.text
    assert "mcp-session-id" not in opened.headers
    assert listed.status_code == 200, listed.text
    assert '"list_sessions"' in listed.text


async def test_daemon_replaced_mid_request_is_reported_in_bounded_time(
    daemon_env: Harness, flask_server: str
) -> None:
    """2 calls killed with their daemon, replaced at once: BOTH still end, reported.

    The replacement answers every renewal, so "gone" is never proven: the changed
    instance is the only evidence, and it has to be enough on its own. And it has to
    reach every call that was on the dead daemon, not just the first to notice: Claude
    Code sends tool calls in parallel, and the second one must not hang.
    """
    cfg = ServerConfig.from_env()
    old_pid = _running_daemon(cfg, daemon_env)
    navigate = {
        "profile": "inflight",
        "url": f"{flask_server}/api/slow?seconds=30",
        "timeout": 60000,
    }

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        calls = [asyncio.ensure_future(proxy.call_tool("navigate", navigate)) for _ in range(2)]
        assert await session_registered(cfg), "the slow navigate never reached the daemon"
        new_pid = await asyncio.to_thread(_replace_daemon, cfg, daemon_env, old_pid)

        for call in calls:
            assert await verdict_within(call, 20.0) == recovery.RESTARTED_MESSAGE

        listing = tool_text(await proxy.call_tool("list_sessions", {}))
        assert "No active sessions" in listing
        after = probe_health(cfg, ENDPOINT)
        assert after is not None
        assert int(after["pid"]) == new_pid, "the proxy spawned a second replacement"
