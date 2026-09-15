"""Cancelling a fetch reaps its child within a deadline, whatever the child prints.

asyncio resolves ``Process.wait()`` only once the process has exited AND every pipe has
reported EOF, and a ``StreamReader`` holding more than twice its limit (128 KiB) unread
pauses the pipe, so that EOF is never read while nothing consumes the stream. The parent
stops consuming stderr the moment it is cancelled, so a child that prints a backlog after
that point, then dies, left ``updater/child.py`` awaiting an exit it could never observe:
a shutdown hang, after the terminate deadline had already been spent.

The child is the real ``python -m camoufox_mcp.updater.fetch`` spawn, reached through the
one environment ``ServerConfig.child_env`` copies to it: a ``sitecustomize`` on
``PYTHONPATH`` arms a SIGTERM handler that prints the backlog and exits, then blocks. No
duration is waited on: the test waits for the child to report it is armed, cancels, and
waits for the cancellation to complete, deadline as guardrail.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import TYPE_CHECKING

from camoufox_mcp import updater
from tests.updater_harness import config_for
from tests.waits import poll_until

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    import pytest

# Past the reader's pause point (2 x 64 KiB) plus a full kernel pipe (64 KiB on Linux),
# so the child is still blocked in its write when the parent stops reading.
BACKLOG_BYTES = 256 * 1024
PID_FILE_VAR = "TEST_FETCH_CHILD_PIDFILE"

SITECUSTOMIZE = f"""\
import os, signal, sys, threading

def on_term(signum, frame):
    sys.stderr.buffer.write(b"x" * {BACKLOG_BYTES} + b"\\n")
    sys.stderr.buffer.flush()
    os._exit(0)

signal.signal(signal.SIGTERM, on_term)
# Written under a temporary name and renamed: the parent polls for the file, and a
# rename lands the pid and the file in the same instant, so it never reads it empty.
pid_file = os.environ[{PID_FILE_VAR!r}]
with open(pid_file + ".tmp", "w") as f:
    f.write(str(os.getpid()))
os.replace(pid_file + ".tmp", pid_file)
threading.Event().wait()
"""


async def test_a_cancelled_fetch_reaps_a_child_with_a_stderr_backlog(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hook_dir = tmp_path / "hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    pid_file = tmp_path / "child.pid"
    config = config_for(
        data_dir,
        monkeypatch,
        CAMOUFOX_AUTO_UPDATE="true",
        PYTHONPATH=str(hook_dir),
        **{PID_FILE_VAR: str(pid_file)},
    )

    fetch = asyncio.create_task(updater.fetch_in_child(config, "geoip"))
    try:
        _, armed = await poll_until(_probe(pid_file.exists), bool)
        assert armed, "the fetch child never reported its SIGTERM handler armed"
        pid = int(pid_file.read_text(encoding="utf-8"))

        fetch.cancel()
        _, done = await poll_until(_probe(fetch.done), bool)
        assert done, "cancelling the fetch did not complete: the child's exit was never reaped"
        assert fetch.cancelled(), "the cancellation must propagate, not be absorbed"
        assert not _alive(pid), "the child must be reaped, not left as an orphan or a zombie"
    finally:
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)


def _probe(condition: Callable[[], bool]) -> Callable[[], Awaitable[bool]]:
    async def probe() -> bool:
        return condition()

    return probe


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
