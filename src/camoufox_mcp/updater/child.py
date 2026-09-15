"""Run 1 Camoufox fetch in a process of its own, so nothing it prints reaches this one.

This process never assigns ``sys.stdout`` or ``sys.stderr``. A redirect is process-wide
whichever thread enters it, and fastmcp 4 suspends between our lifespan's ``yield`` and
the stdio transport claiming fd 1: a background refresh that swapped the streams from a
worker thread in that window handed the transport a ``StringIO``, and the server died
before its first reply. So the chatty work runs in a child whose stdin and stdout are
the null device, with a bounded tail of its stderr kept as the failure message.

The child is ``python -m camoufox_mcp.updater.fetch <asset>`` (:mod:`.fetch`), spawned
with a copy of the environment so it re-derives the same :class:`ServerConfig`. It is
awaited to completion; cancelling the awaiting task terminates it under a deadline, so
a shutdown never waits on a black-holed download.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
from typing import TYPE_CHECKING

from camoufox_mcp.deadlines import bounded
from camoufox_mcp.updater.errors import FetchError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.updater.fetch import FetchAsset

    Fetcher = Callable[[ServerConfig, FetchAsset], Awaitable[None]]

logger = logging.getLogger(__name__)

FETCH_MODULE = "camoufox_mcp.updater.fetch"
STDERR_TAIL_BYTES = 2000
STDERR_CHUNK_BYTES = 4096
# How long a terminated child gets to exit before it is killed: it is mid-download or
# mid-extract, and holds nothing this process needs to see written.
TERMINATE_TIMEOUT_S = 5.0
# How long a killed child gets to be reaped. SIGKILL cannot be caught, so only a process
# stuck in uninterruptible I/O, or a grandchild holding the stderr pipe open, outlives it.
KILL_TIMEOUT_S = 5.0


async def fetch_in_child(config: ServerConfig, asset: FetchAsset) -> None:
    """Fetch ``asset`` in a child process and return once it has exited successfully.

    Raises :class:`FetchError` on a non-zero exit, carrying the last
    :data:`STDERR_TAIL_BYTES` of the child's stderr. On cancellation the child is
    terminated (killed after :data:`TERMINATE_TIMEOUT_S`) before the cancellation
    propagates.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        FETCH_MODULE,
        asset,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=config.child_env(),
        # No console window under a GUI host on Windows; 0 everywhere else, where the
        # keyword is only accepted at that value.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        tail = await _stderr_tail(process.stderr)
        returncode = await process.wait()
    except asyncio.CancelledError:
        await _terminate(process)
        raise
    if returncode != 0:
        raise FetchError(asset, returncode, tail)


async def _stderr_tail(stream: asyncio.StreamReader | None) -> str:
    """Drain ``stream`` to EOF, keeping only its last :data:`STDERR_TAIL_BYTES`.

    Drained rather than read at the end so a talkative child never blocks on a full
    pipe, and bounded so a talkative child never grows this process either.
    """
    if stream is None:
        return ""
    tail = b""
    while chunk := await stream.read(STDERR_CHUNK_BYTES):
        tail = (tail + chunk)[-STDERR_TAIL_BYTES:]
    return tail.decode("utf-8", errors="replace").strip()


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Stop ``process`` and reap it, every step under a deadline, whatever it prints.

    The wait drains stderr rather than merely awaiting the exit. asyncio resolves
    ``Process.wait()`` only once the process has exited AND every pipe has reported EOF,
    and a ``StreamReader`` holding more than twice its limit (128 KiB) unread pauses the
    pipe, so that EOF is never observed while nothing reads: a child that printed a
    backlog after this side stopped reading, then died, left a plain ``wait()`` pending
    forever, and the shutdown with it.
    """
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    if await _reaped_within(process, TERMINATE_TIMEOUT_S):
        return
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    if not await _reaped_within(process, KILL_TIMEOUT_S):
        logger.warning(
            "Camoufox fetch child %s did not exit within %.0fs of SIGKILL; leaving it",
            process.pid,
            KILL_TIMEOUT_S,
        )


async def _reaped_within(process: asyncio.subprocess.Process, timeout: float) -> bool:
    """Discard the rest of stderr, then wait for the exit that EOF makes observable."""

    async def reap() -> None:
        await _stderr_tail(process.stderr)
        await process.wait()

    try:
        await bounded(reap(), timeout)
    except TimeoutError:
        return False
    return True
