"""The pure rules behind leases, on fake clocks: nothing here can be reached in bounded
time through a real daemon (a suspend, a 15 minute clamp, an advert flipping between 2
requests), so these are the focused tests the suite allows for pure logic."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP

from camoufox_mcp.daemon.endpoint import Conn
from camoufox_mcp.daemon.endpoint_resolving import resolving_client
from camoufox_mcp.daemon.errors import LeaseClosedError, LeaseLimitError
from camoufox_mcp.daemon.identity import DaemonInstance
from camoufox_mcp.daemon.lease import WAKE_POLL_S, DaemonLease
from camoufox_mcp.daemon.lease_client import GONE, UNKNOWN, Alive, LeaseClient
from camoufox_mcp.daemon.lease_routes import register_lease_routes
from camoufox_mcp.daemon.leases import MAX_LEASE_TTL_S, MAX_LEASES, MIN_LEASE_TTL_S, LeaseTable
from camoufox_mcp.daemon.suspend import SuspendDetector
from tests.fake_clocks import Clocks

if TYPE_CHECKING:
    from camoufox_mcp.daemon.lease_client import Probe


def test_lease_table_expiry_release_and_vacancy() -> None:
    clock = Clocks()
    table = LeaseTable(clock=lambda: clock.mono)
    assert table.vacated_at() is None

    assert table.grant("a", 10.0) == 10.0
    assert table.grant("b", 0.01) == MIN_LEASE_TTL_S
    assert table.grant("c", 10_000) == MAX_LEASE_TTL_S
    assert table.live_count() == 3

    clock.advance(5)
    assert table.live_count() == 2  # b lapsed
    assert table.release("c") is True
    assert table.release("c") is False
    assert table.vacated_at() is None  # a is still live

    clock.advance(10)
    assert table.live_count() == 0
    assert table.vacated_at() == 1010.0  # a's expiry, not the time it was noticed

    table.grant("d", 3.0)
    assert table.vacated_at() is None
    clock.advance(1)
    assert table.release("d") is True
    assert table.vacated_at() == clock.mono


def test_lease_table_limit_and_suspend_refresh() -> None:
    clock = Clocks()
    table = LeaseTable(clock=lambda: clock.mono)
    for index in range(MAX_LEASES):
        table.grant(f"{index:032x}", 3.0)
    with pytest.raises(LeaseLimitError):
        table.grant("f" * 32, 3.0)
    table.grant(f"{0:032x}", 3.0)  # renewing a live id is never refused

    clock.advance(2.5)
    table.refresh_all()
    clock.advance(2.5)
    assert table.live_count() == MAX_LEASES


@pytest.mark.parametrize(
    ("advance", "expected"),
    [
        (lambda c: c.advance(15), False),
        (lambda c: c.advance(3600, suspended=True), True),  # monotonic froze
        (lambda c: c.advance(3600), True),  # monotonic counted the sleep (Windows)
        (lambda c: setattr(c, "wall", c.wall - 3600) or c.advance(15), False),  # NTP back
    ],
)
def test_suspend_detector(advance: Any, expected: bool) -> None:
    clock = Clocks()
    detector = SuspendDetector(15.0, mono=lambda: clock.mono, wall=lambda: clock.wall)
    advance(clock)
    assert detector.tick() is expected


async def test_a_closed_lease_table_refuses_every_grant() -> None:
    clock = Clocks()
    table = LeaseTable(clock=lambda: clock.mono)
    table.grant("a", 90.0)
    table.close()
    with pytest.raises(LeaseClosedError):
        table.grant("a", 90.0)
    with pytest.raises(LeaseClosedError):
        table.grant("b", 90.0)


@dataclass
class _Channel:
    answers: list[Probe]
    renewals: int = 0
    released: bool = False
    log: list[str] = field(default_factory=list)

    async def renew(self) -> Probe:
        self.renewals += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    async def release(self) -> None:
        self.released = True

    async def aclose(self) -> None:
        self.log.append("closed")


_A = Alive(DaemonInstance(pid=1, started_at="t1"))
_B = Alive(DaemonInstance(pid=2, started_at="t2"))


async def test_a_replacement_is_noticed_exactly_once() -> None:
    lease = DaemonLease(_Channel([_A, _A, _B, _B, _A]), 30.0)
    seen = []
    for _ in range(5):
        await lease.check()
        seen.append(lease.take_notice())
    assert seen == [False, False, True, False, True]

    respawned = DaemonLease(_Channel([_A, _B]), 30.0)
    await respawned.check()
    await respawned.adopt_current()
    assert respawned.take_notice() is False

    # The fresh daemon too busy to answer the adopting renewal: the dead instance must
    # not stay bound, or its first answer would read as a second replacement.
    busy = DaemonLease(_Channel([_A, UNKNOWN, _B, _B]), 30.0)
    await busy.check()
    await busy.adopt_current()
    assert busy.bound is None
    await busy.check()
    assert busy.bound == _B.instance
    assert busy.take_notice() is False


async def test_heartbeat_renews_on_wake_within_one_poll() -> None:
    clock = Clocks()
    channel = _Channel([_A])
    polls: list[float] = []

    async def sleep(seconds: float) -> None:
        polls.append(seconds)
        if len(polls) == 1:
            clock.advance(3600, suspended=True)  # the machine slept inside this poll
        elif len(polls) == 3:
            raise asyncio.CancelledError
        else:
            clock.advance(seconds)

    lease = DaemonLease(
        channel, 30.0, mono=lambda: clock.mono, wall=lambda: clock.wall, sleep=sleep
    )
    await lease.check()
    with pytest.raises(asyncio.CancelledError):
        await lease.heartbeat()
    assert polls == [WAKE_POLL_S, WAKE_POLL_S, WAKE_POLL_S]
    # 1 initial check, 1 renewal on the first poll after the wake, none on the next.
    assert channel.renewals == 2


async def test_lifespan_releases_on_exit_and_survives_a_dead_daemon() -> None:
    channel = _Channel([GONE])
    lease = DaemonLease(channel, 30.0)
    async with lease.lifespan(None):
        pass
    assert channel.released
    assert channel.log == ["closed"]


class _FlippingEndpoint:
    """An endpoint whose advert can be repointed between 2 requests."""

    def __init__(self) -> None:
        self.conn: Conn | None = None
        self.transports: dict[str, httpx.AsyncBaseTransport] = {}

    def resolve(self, _config: object) -> Conn | None:
        return self.conn

    def async_transport(self, conn: Conn) -> httpx.AsyncBaseTransport:
        return self.transports[conn.base_url]


def _app(name: str) -> Any:
    async def app(scope: dict, receive: Any, send: Any) -> None:
        headers = dict(scope["headers"])
        body = f"{name} {headers.get(b'authorization', b'-').decode()}".encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return app


async def test_resolving_transport_follows_the_advert() -> None:
    endpoint = _FlippingEndpoint()
    endpoint.transports = {
        "http://127.0.0.1:1111": httpx.ASGITransport(app=_app("first")),
        "http://127.0.0.1:2222": httpx.ASGITransport(app=_app("second")),
    }
    client = resolving_client(endpoint, None, timeout=1.0)  # type: ignore[arg-type]
    async with client:
        with pytest.raises(httpx.ConnectError):
            await client.get("/health")

        endpoint.conn = Conn(base_url="http://127.0.0.1:1111", token="one")
        assert (await client.get("/health")).text == "first Bearer one"

        endpoint.conn = Conn(base_url="http://127.0.0.1:2222", token="two")
        assert (await client.get("/health")).text == "second Bearer two"


async def test_a_closing_daemon_reads_as_gone() -> None:
    """Once the daemon has decided to exit, its lease route answers "gone" at once."""
    instance = DaemonInstance(pid=1, started_at="t1")
    table = LeaseTable()
    server = FastMCP("closing")
    register_lease_routes(server, table, instance)
    endpoint = _FlippingEndpoint()
    endpoint.conn = Conn(base_url="http://127.0.0.1:1111", token=None)
    endpoint.transports = {endpoint.conn.base_url: httpx.ASGITransport(app=server.http_app())}
    channel = LeaseClient(None, endpoint, "a" * 32, 90.0)  # type: ignore[arg-type]
    try:
        assert await channel.renew() == Alive(instance)
        table.close()
        assert await channel.renew() == GONE
    finally:
        await channel.aclose()
