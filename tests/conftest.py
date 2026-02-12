from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import urllib.request
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from camoufox_mcp.server import mcp

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

FLASK_URL = "http://127.0.0.1:5123"


@pytest.fixture(scope="session", autouse=True)
def _profiles_dir() -> Iterator[str]:
    """Session-scoped temp profiles dir, set before any Client triggers the lifespan."""
    profiles_dir = tempfile.mkdtemp(prefix="camoufox_test_profiles_")
    os.environ["CAMOUFOX_PROFILES_DIR"] = profiles_dir
    yield profiles_dir
    os.environ.pop("CAMOUFOX_PROFILES_DIR", None)
    shutil.rmtree(profiles_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def flask_server() -> Iterator[str]:
    """Start Flask test server in a background thread for the whole session."""
    from tests.server import app

    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=5123, use_reloader=False),
        daemon=True,
    )
    server.start()

    for _ in range(50):
        try:
            urllib.request.urlopen(FLASK_URL, timeout=0.5)
            break
        except OSError:
            time.sleep(0.1)

    yield FLASK_URL


@pytest.fixture
async def client(flask_server: str) -> AsyncIterator[Client]:
    """In-memory MCP client — fresh per test, no browser carryover."""
    async with Client(mcp) as c:
        yield c
        await c.call_tool("kill_session", {})
