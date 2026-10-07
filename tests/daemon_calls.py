"""Waits on a proxy call that is in flight while its daemon dies, shared by the
recovery and replacement scenarios."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.daemon.spawn import probe_health
from tests.daemon_harness import ENDPOINT
from tests.waits import poll_until

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig


async def session_registered(cfg: ServerConfig, deadline: float = 60.0) -> bool:
    """Block until the daemon reports the session the in-flight call just created.

    Proof that the request really is in flight, rather than a sleep long enough to
    probably be: ``navigate`` registers the session before it starts loading the URL,
    so ``active_sessions == 1`` means the call is inside the daemon and still running.
    Without this the kill could land before the request was even sent, silently
    degrading the test into the between-calls case.
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


async def verdict_within(call: asyncio.Future, budget: float) -> str:
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
