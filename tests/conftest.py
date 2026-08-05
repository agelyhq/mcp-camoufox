from __future__ import annotations

import threading
import urllib.request
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from tests.helpers import FLASK_PORT, server_for
from tests.waits import poll_until_sync

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from fastmcp import FastMCP

FLASK_URL = f"http://127.0.0.1:{FLASK_PORT}"

# A title only our index carries. The guard used to accept any answer on the port, so a
# foreign server left over from an earlier run satisfied it while this run's own bind had
# failed with EADDRINUSE: the session then reported 37 navigation failures across unrelated
# tests, and none of them named the port. An assertion satisfied by something other than
# the thing it is about is worth nothing.
_INDEX_MARKER = b"MCP Tool Test Pages"


def _ours_is_answering() -> bool:
    try:
        with urllib.request.urlopen(FLASK_URL, timeout=0.5) as answer:
            return _INDEX_MARKER in answer.read()
    except OSError:
        return False


@pytest.fixture(scope="session")
def flask_server() -> Iterator[str]:
    """Start the Flask test server in a background thread for the whole session."""
    from tests.server import app

    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=FLASK_PORT, use_reloader=False),
        daemon=True,
    )
    server.start()

    if not poll_until_sync(_ours_is_answering, deadline=5.0):
        pytest.fail(
            f"no test server of ours answered on {FLASK_URL}. If the port is already taken, "
            f"set TEST_FLASK_PORT: without this check every browser test fails on a blank "
            f"page instead, which reads as 37 broken tests rather than 1 busy port."
        )

    yield FLASK_URL


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Per-test data directory (profiles + telemetry logs live here)."""
    return tmp_path / "camoufox-data"


@pytest.fixture
def mcp_server(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> FastMCP:
    """Build a fresh in-process server bound to an isolated, headless config.

    A new server (and therefore a fresh SessionManager) is built per test so its
    asyncio primitives never leak across pytest's per-test event loops, and so each
    test gets a clean profile/telemetry directory.
    """
    return server_for(monkeypatch, data_dir)


@pytest.fixture
async def client(mcp_server: FastMCP, flask_server: str) -> AsyncIterator[Client]:
    """In-memory MCP client. On exit the lifespan closes every open session."""
    async with Client(mcp_server) as c:
        yield c
