"""Daemon survival: a refused shutdown must not cost a live daemon its address, and a
daemon that dies mid-conversation must be back for the next call."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import recovery, spawn
from camoufox_mcp.daemon.proxy import build_proxy
from camoufox_mcp.daemon.spawn import ensure_daemon, probe_health
from tests.daemon_harness import (
    ENDPOINT,
    Harness,
    advert_path,
    daemon_session,
    hard_kill,
    mismatched_identity,
    wait_gone,
)
from tests.helpers import tool_text
from tests.waits import poll_until

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from camoufox_mcp.daemon.endpoint import DaemonEndpoint

# How long the caller may wait, after the daemon dies, for a verdict on a request that
# was in flight when it died. Detection costs 2 liveness probes (see recovery.py) and
# the verdict costs one respawn, so this is generous; the failure it guards against is
# unbounded, measured past 600s.
_INFLIGHT_VERDICT_BUDGET_S = 45.0


@pytest.fixture
def daemon_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """Isolated daemon for one test (see :mod:`tests.daemon_harness`)."""
    yield from daemon_session(monkeypatch)


async def test_refused_shutdown_leaves_the_live_advert_alone(
    daemon_env: Harness, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session landing between the health probe and the shutdown must not orphan the daemon.

    The proxy sees an idle mismatched daemon and asks it to leave; by then a session
    exists, so the daemon refuses. The advert it published is still its only reachable
    control channel, so nothing may unlink it.
    """
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        await proxy.call_tool("navigate", {"profile": "racing", "url": flask_server})

    before = probe_health(cfg, ENDPOINT)
    assert before is not None
    assert before["active_sessions"] == 1
    daemon_env.track(int(before["pid"]))

    monkeypatch.setattr(spawn, "local_identity", mismatched_identity)
    monkeypatch.setattr(spawn, "ADDRESS_REMOVAL_DEADLINE_S", 1.0)
    monkeypatch.setattr(spawn, "probe_health", _probe_hiding_the_first_session())

    ensure_daemon(cfg, ENDPOINT)

    after = probe_health(cfg, ENDPOINT)
    assert after is not None, "the live daemon's advert was removed"
    assert after["pid"] == before["pid"], "a replacement daemon took the address"
    assert after["active_sessions"] == 1, "the live session was lost"
    assert advert_path(cfg).exists()


def _probe_hiding_the_first_session() -> Callable[[ServerConfig, DaemonEndpoint], dict | None]:
    """Report the daemon as idle on the first probe only, reproducing the race.

    The real race is a session landing microseconds after the probe answered; forging
    that one answer makes it deterministic instead of timing-dependent.
    """
    real_probe = spawn.probe_health
    seen: list[int] = []

    def probe(config: ServerConfig, endpoint: DaemonEndpoint) -> dict | None:
        health = real_probe(config, endpoint)
        seen.append(1)
        if len(seen) == 1 and health is not None:
            return {**health, "active_sessions": 0}
        return health

    return probe


async def test_daemon_death_between_calls_is_reported_then_recovered(
    daemon_env: Harness, flask_server: str
) -> None:
    """A daemon killed BETWEEN calls costs one call, not the rest of the conversation.

    This is the easy half: the next request finds a closed control channel and the
    transport raises, which is the only thing the recovery middleware used to react
    to. The hard half, a daemon killed while a request is already in flight, is
    covered by the test below and produces no exception at all.
    """
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    first = probe_health(cfg, ENDPOINT)
    assert first is not None
    old_pid = int(first["pid"])
    daemon_env.track(old_pid)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        await proxy.call_tool("navigate", {"profile": "doomed", "url": flask_server})

        hard_kill(old_pid)
        assert wait_gone(cfg), "the daemon survived SIGKILL"

        # The concrete type depends on where the transport broke; the message is the contract.
        with pytest.raises(Exception) as excinfo:
            await proxy.call_tool("list_sessions", {})
        message = str(excinfo.value)
        assert "daemon" in message.lower()
        assert "restart" in message.lower()
        assert "session" in message.lower()

        health = probe_health(cfg, ENDPOINT)
        assert health is not None, "no daemon was respawned"
        assert int(health["pid"]) != old_pid
        daemon_env.track(int(health["pid"]))

        # The next call reaches the new daemon, which owns no browser sessions.
        listing = tool_text(await proxy.call_tool("list_sessions", {}))
        assert "doomed" not in listing


async def test_daemon_death_mid_request_is_reported_in_bounded_time(
    daemon_env: Harness, flask_server: str
) -> None:
    """A daemon killed WHILE a request is in flight must not hang the conversation.

    Killing it between calls only proves the path that already worked. Here the
    request is sent, the daemon dies holding it, and no exception is ever raised:
    the streamable-HTTP response simply never arrives and the read timeout is far
    longer than any conversation can wait. The caller must still get the error and
    a working daemon for the next call.
    """
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    first = probe_health(cfg, ENDPOINT)
    assert first is not None
    old_pid = int(first["pid"])
    daemon_env.track(old_pid)

    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        call = asyncio.ensure_future(
            proxy.call_tool(
                "navigate",
                {
                    "profile": "inflight",
                    "url": f"{flask_server}/api/slow?seconds=30",
                    "timeout": 60000,
                },
            )
        )
        assert await _session_registered(cfg), "the slow navigate never reached the daemon"

        hard_kill(old_pid)
        assert await asyncio.to_thread(wait_gone, cfg), "the daemon survived SIGKILL"

        # The budget is enforced by _verdict_within, which fails the test on expiry;
        # re-measuring the same window here could only ever fail on a slow machine.
        message = await _verdict_within(call, _INFLIGHT_VERDICT_BUDGET_S)
        # The exact message, not keywords: UNRECOVERED_MESSAGE also says "restarted",
        # so a substring check would accept a failed respawn as a success here.
        assert message == recovery.RESTARTED_MESSAGE

        health = probe_health(cfg, ENDPOINT)
        assert health is not None, "no daemon was respawned"
        assert int(health["pid"]) != old_pid
        daemon_env.track(int(health["pid"]))


async def test_a_slow_call_on_a_healthy_daemon_is_never_cancelled(
    daemon_env: Harness, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watchdog separates "the daemon is gone" from "this call is taking a while".

    The single request below stays outstanding for several watch intervals, so the
    liveness probe runs repeatedly against a daemon that is perfectly healthy. What is
    asserted is that structure, not a duration: more probes ran than it takes to
    condemn a daemon, every one of them answered "still there", and the call still
    returned its result. Any version of the watchdog that gives up on elapsed time
    instead of on proof of death fails here, which is the regression this pairs with
    the test above.
    """
    cfg = ServerConfig.from_env()
    ensure_daemon(cfg, ENDPOINT)
    health = probe_health(cfg, ENDPOINT)
    assert health is not None
    daemon_env.track(int(health["pid"]))

    probes = _counted_liveness_probes(monkeypatch)

    seconds = 5 * recovery.WATCH_INTERVAL_S
    async with Client(build_proxy(cfg, ENDPOINT)) as proxy:
        result = tool_text(
            await proxy.call_tool(
                "navigate",
                {
                    "profile": "slowpoke",
                    "url": f"{flask_server}/api/slow?seconds={seconds}",
                    "timeout": 60000,
                },
            )
        )

    # Not "no probe ever answered gone": the product tolerates a lone refusal (a full
    # accept backlog clears in milliseconds), which is why it demands 2 in a row. The
    # returned result is the proof that no such run was ever reached.
    assert "Navigated to:" in result
    assert len(probes) > recovery.DEATH_CONFIRMATIONS, (
        f"the call was probed {len(probes)} times, too few to prove the watchdog let a "
        "healthy daemon's call run past the point where it condemns a dead one"
    )


def _counted_liveness_probes(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Record every watchdog liveness probe, and its answer, as it happens.

    ``proven_gone`` is the only thing ``_call_watched`` consults, so the length of
    this list is exactly how many times the watchdog asked whether the daemon holding
    the outstanding call still existed. Appending from the worker thread
    ``asyncio.to_thread`` runs it on is safe: list.append is atomic.
    """
    real_probe = recovery.proven_gone
    answers: list[bool] = []

    def counting_probe(config: ServerConfig, endpoint: DaemonEndpoint) -> bool:
        gone = real_probe(config, endpoint)
        answers.append(gone)
        return gone

    monkeypatch.setattr(recovery, "proven_gone", counting_probe)
    return answers


async def _session_registered(cfg: ServerConfig, deadline: float = 60.0) -> bool:
    """Block until the daemon reports the session the in-flight call just created.

    Proof that the request really is in flight, rather than a sleep long enough to
    probably be: ``navigate`` registers the session before it starts loading the URL,
    so ``active_sessions == 1`` means the call is inside the daemon and still running.
    Without this the kill could land before the request was even sent, silently
    degrading this test into the between-calls case that already passes.
    """

    async def health() -> dict | None:
        return await asyncio.to_thread(probe_health, cfg, ENDPOINT)

    _, registered = await poll_until(
        health,
        lambda h: h is not None and int(h["active_sessions"]) >= 1,
        deadline=deadline,
        interval=0.1,
    )
    return registered


async def _verdict_within(call: asyncio.Future, budget: float) -> str:
    """The failure message the in-flight call ends with, within ``budget`` seconds.

    The hang IS the defect, so it must never be mistaken for the expected error: a
    ``pytest.raises(Exception)`` would happily accept the ``TimeoutError`` that a hang
    produces here and report a pass.
    """
    try:
        await asyncio.wait_for(call, timeout=budget)
    except TimeoutError:
        pytest.fail(f"the call was still in flight {budget:.0f}s after the daemon died")
    except Exception as exc:
        return str(exc)
    pytest.fail("the call returned a result from a daemon that no longer exists")
