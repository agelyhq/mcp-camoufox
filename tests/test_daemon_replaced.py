"""A daemon replaced behind a connected proxy must cost that proxy one call, not the rest
of its conversation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import recovery
from camoufox_mcp.daemon.proxy import build_proxy
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health
from tests.daemon_harness import (
    ENDPOINT,
    Harness,
    daemon_diagnostics,
    daemon_session,
    hard_kill,
    wait_gone,
)
from tests.helpers import tool_text

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Isolated daemon for one test (see :mod:`tests.daemon_harness`)."""
    yield from daemon_session(monkeypatch)


async def test_daemon_respawned_by_another_proxy_is_reported_then_recovered(
    daemon_env: Harness,
) -> None:
    """Proxy A idles while its daemon exits and another proxy spawns a new one.

    The new daemon answers ``/health``, so A sees no dead daemon, yet A's cached backend
    session id belongs to the old process and draws a 404 on every call. A must report
    that once and reach the new daemon on the following call.
    """
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    first = probe_health(cfg, ENDPOINT)
    assert first is not None
    old_pid = int(first["pid"])
    daemon_env.track(old_pid)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        tool_text(await proxy.call_tool("list_sessions", {}))

        hard_kill(old_pid)
        assert wait_gone(cfg), daemon_diagnostics(cfg, "the daemon survived SIGKILL")
        # What another proxy starting up does: it finds no daemon and spawns one.
        ensure_daemon(cfg, ENDPOINT)
        replacement = probe_health(cfg, ENDPOINT)
        assert replacement is not None, "no replacement daemon came up"
        assert int(replacement["pid"]) != old_pid
        daemon_env.track(int(replacement["pid"]))

        with pytest.raises(Exception) as excinfo:
            await proxy.call_tool("list_sessions", {})
        assert str(excinfo.value) == recovery.RESTARTED_MESSAGE

        listing = tool_text(await proxy.call_tool("list_sessions", {}))
        assert "No active sessions" in listing

        after = probe_health(cfg, ENDPOINT)
        assert after is not None
        assert after["pid"] == replacement["pid"], "the proxy spawned a second replacement"
