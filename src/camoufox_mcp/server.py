from __future__ import annotations

import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from camoufox_mcp.browser import BrowserManager, ServerConfig
from camoufox_mcp.tools import register_all_tools

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


def _ensure_browser_binary() -> None:
    from camoufox.exceptions import CamoufoxNotInstalled
    from camoufox.pkgman import launch_path

    try:
        launch_path()
    except CamoufoxNotInstalled:
        logger.info("Camoufox binary not found. Running 'camoufox fetch'...")
        subprocess.run(
            [sys.executable, "-m", "camoufox", "fetch"],
            check=True,
        )
        logger.info("Camoufox binary installed successfully.")


def _check_s3(config: ServerConfig) -> None:
    """Verify S3 bucket is reachable at startup. Raises RuntimeError if not."""
    if not config.s3:
        msg = (
            "S3 is not configured. Set CAMOUFOX_S3_ENDPOINT, CAMOUFOX_S3_ACCESS_KEY, "
            "CAMOUFOX_S3_SECRET_KEY, CAMOUFOX_S3_BUCKET to use profiles."
        )
        raise RuntimeError(msg)
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=config.s3.endpoint_url,
        aws_access_key_id=config.s3.access_key,
        aws_secret_access_key=config.s3.secret_key,
        region_name=config.s3.region,
    )
    try:
        s3.head_bucket(Bucket=config.s3.bucket)
        logger.info("S3 bucket '%s' reachable at %s", config.s3.bucket, config.s3.endpoint_url)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        msg = f"S3 bucket '{config.s3.bucket}' not accessible ({code}): {exc}"
        raise RuntimeError(msg) from exc


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[BrowserManager]:
    config = ServerConfig.from_env()
    _check_s3(config)
    manager = BrowserManager(config)
    try:
        yield manager
    finally:
        await manager.stop_session()


mcp = FastMCP(
    "Camoufox Browser",
    lifespan=lifespan,
    instructions=(
        "Browser automation server using Camoufox (anti-detect Firefox).\n\n"
        "Workflow:\n"
        "1. Use navigate to load a page (auto-starts the browser on first call)\n"
        "2. Use take_snapshot to see the page structure and get element UIDs\n"
        "3. Use click/fill/press_key to interact with elements by UID\n"
        "4. Use take_snapshot again after interactions to see updated state\n"
        "5. Use take_screenshot for visual verification when needed\n"
        "6. Use kill_session to reset the browser when done or to start fresh\n\n"
        "UIDs (e.g., e0, e1, e2) are assigned by take_snapshot and are valid "
        "until the next navigation or take_snapshot call. Always call "
        "take_snapshot before interacting with elements."
    ),
)

register_all_tools(mcp)


def main() -> None:
    import datetime
    import os

    log_dir = os.path.expanduser("~/.cache/camoufox-mcp/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, datetime.datetime.now().strftime("%Y%m%d_%H%M%S.log"))
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_file)],
    )
    _ensure_browser_binary()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
