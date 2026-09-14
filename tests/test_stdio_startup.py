"""A fresh install answers its first request while its background refresh is due.

The one scenario the in-process suite cannot see: the real entry point, over a real
stdio transport, with an EMPTY data dir so the 24h refresh is due at the very start.
That refresh once redirected the process streams from a worker thread while the
transport was still about to read ``sys.stdout``; fastmcp 4 suspends between our
lifespan and that read, and every start died before ``initialize`` was answered, with
the host reporting "Connection closed". The stamp is written only by a completed
refresh, so a crashed start re-armed the race on every restart.

Offline by construction: ``HTTP_PROXY``/``HTTPS_PROXY`` name a loopback port nothing
listens on, so the refresh fails fast and fail-open, and the pinned build is already on
disk (asserted first, the way :mod:`tests.test_autoupdate_pin` does) so no cold install
is attempted. Every wait is a condition with a deadline as guardrail; nothing sleeps.

Which stack this runs on decides what it can prove. Measured against the pre-fix
updater: RED on fastmcp 4.0.3 / mcp 2.2.0 ("the server closed stdout before answering
request 1"), GREEN on the locked fastmcp 3.4.4 / mcp 1.26.0, where no suspension point
lets the refresh start before the transport has claimed the streams. ``make test`` runs
the lock, so it passes here with the bug present; ``make test-latest`` (also in
``release.yml``) runs this module on the unlocked resolution ``uv tool install`` gives
users, which is the run that fails when the streams are swapped again. A relock that
lands on fastmcp 4 makes ``make test`` discriminating too; a relock that stays below
does not, and the second run must stay.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from camoufox_mcp.config import DEFAULT_BROWSER_VERSION
from camoufox_mcp.updater import STAMP_NAME, installed_build
from tests.helpers import isolate_camoufox_env
from tests.waits import poll_until

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# The first reply waits for camoufox to import and the build to be checked: generous,
# because it bounds a hung server rather than timing a fast one.
REPLY_DEADLINE_S = 60.0
EXIT_DEADLINE_S = 30.0
REFRESH_LOG_LINE = "Background Camoufox refresh failed"

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "tests.test_stdio_startup", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _refused_port() -> int:
    """A loopback port nothing listens on: bound, released, and never reused this fast."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _send(process: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))


async def _reply_to(process: asyncio.subprocess.Process, request_id: int) -> dict[str, Any]:
    """The response carrying ``request_id``, skipping notifications the server emits."""
    assert process.stdout is not None
    while True:
        line = await asyncio.wait_for(process.stdout.readline(), REPLY_DEADLINE_S)
        assert line, f"the server closed stdout before answering request {request_id}"
        message = json.loads(line)
        if message.get("id") == request_id:
            return message


def _server_log(data_dir: Path) -> str:
    return "".join(
        path.read_text(encoding="utf-8")
        for path in sorted((data_dir / "logs").glob("server-*.log"))
    )


async def test_a_due_refresh_never_costs_the_first_reply(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert installed_build(DEFAULT_BROWSER_VERSION) is not None, (
        f"the suite's pinned build {DEFAULT_BROWSER_VERSION} is not installed"
    )
    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_AUTO_UPDATE="true")
    refused = f"http://127.0.0.1:{_refused_port()}"
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(var, refused)
    monkeypatch.delenv("NO_PROXY", raising=False)
    stamp = data_dir / STAMP_NAME
    assert not stamp.exists(), "an empty data dir is what makes the refresh due"

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "camoufox_mcp.server",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _send(process, INITIALIZE)
        initialized = await _reply_to(process, 1)
        assert (
            initialized.get("result", {}).get("serverInfo", {}).get("name") == "Camoufox Browser"
        ), initialized
        _send(process, INITIALIZED)
        _send(process, LIST_TOOLS)
        listing = await _reply_to(process, 2)
        names = {tool["name"] for tool in listing.get("result", {}).get("tools", [])}
        assert {"navigate", "snapshot", "list_sessions"} <= names, listing

        # The refresh ran, hit the refused port, and was logged fail-open: the server is
        # still the one answering above, and the log is the only trace it leaves.
        log, seen = await poll_until(
            lambda: asyncio.sleep(0, result=_server_log(data_dir)),
            lambda text: REFRESH_LOG_LINE in text,
            deadline=EXIT_DEADLINE_S,
        )
        assert seen, f"the refused refresh never reached the server log:\n{log}"
        assert "Traceback" not in log, log

        assert process.stdin is not None
        process.stdin.close()
        returncode, exited = await poll_until(
            lambda: asyncio.sleep(0, result=process.returncode),
            lambda code: code is not None,
            deadline=EXIT_DEADLINE_S,
        )
        assert exited, "the server did not exit after its stdin closed"
        assert process.stderr is not None
        stderr = (await asyncio.wait_for(process.stderr.read(), REPLY_DEADLINE_S)).decode(
            "utf-8", errors="replace"
        )
        assert "Traceback" not in stderr, stderr
        assert returncode == 0, f"exit status {returncode}; stderr:\n{stderr}"
        assert not stamp.exists(), "a refresh that failed must not close the 24h throttle"
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
