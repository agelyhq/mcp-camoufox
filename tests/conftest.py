from __future__ import annotations

import os
import threading
import time
import urllib.request
from typing import TYPE_CHECKING

import boto3
import pytest
from fastmcp import Client
from moto.server import ThreadedMotoServer

from camoufox_mcp.server import mcp

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

FLASK_URL = "http://127.0.0.1:5123"
_S3_BUCKET = "camoufox-test-profiles"
_MOTO_PORT = 5124
_MOTO_ENDPOINT = f"http://127.0.0.1:{_MOTO_PORT}"


@pytest.fixture(scope="session", autouse=True)
def _s3_mock() -> Iterator[None]:
    """Start a real moto HTTP server so boto3 calls from threads work correctly."""
    server = ThreadedMotoServer(port=_MOTO_PORT)
    server.start()

    env_vars = {
        "CAMOUFOX_S3_ENDPOINT": _MOTO_ENDPOINT,
        "CAMOUFOX_S3_ACCESS_KEY": "test",
        "CAMOUFOX_S3_SECRET_KEY": "test",
        "CAMOUFOX_S3_BUCKET": _S3_BUCKET,
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
    }
    for k, v in env_vars.items():
        os.environ[k] = v

    boto3.client("s3", region_name="us-east-1", endpoint_url=_MOTO_ENDPOINT).create_bucket(
        Bucket=_S3_BUCKET
    )

    yield

    server.stop()
    for k in env_vars:
        os.environ.pop(k, None)


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
