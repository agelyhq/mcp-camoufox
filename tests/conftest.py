from __future__ import annotations

import threading
import time
import urllib.request
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from fastmcp import FastMCP

FLASK_URL = "http://127.0.0.1:5123"


@pytest.fixture(scope="session")
def flask_server() -> Iterator[str]:
    """Start the Flask test server in a background thread for the whole session."""
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
    monkeypatch.setenv("CAMOUFOX_HEADLESS", "true")
    monkeypatch.setenv("CAMOUFOX_AUTO_UPDATE", "false")
    monkeypatch.setenv("CAMOUFOX_DATA_DIR", str(data_dir))
    monkeypatch.delenv("CAMOUFOX_PROXY", raising=False)
    monkeypatch.delenv("CAMOUFOX_FINGERPRINT_OS", raising=False)
    monkeypatch.delenv("CAMOUFOX_VIEWPORT", raising=False)
    monkeypatch.delenv("CAMOUFOX_LOCALE", raising=False)

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.server import build_server

    return build_server(ServerConfig.from_env())


@pytest.fixture
async def client(mcp_server: FastMCP, flask_server: str) -> AsyncIterator[Client]:
    """In-memory MCP client. On exit the lifespan closes every open session."""
    async with Client(mcp_server) as c:
        yield c
