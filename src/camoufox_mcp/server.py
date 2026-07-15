from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.sessions import SessionManager
from camoufox_mcp.telemetry import TelemetryLogger
from camoufox_mcp.tools import register_all_tools
from camoufox_mcp.tools._base import ToolDeps
from camoufox_mcp.updater import ensure_browser_present, schedule_refresh

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "Browser automation over Camoufox (anti-detect Firefox), with per-profile session "
    "isolation.\n\n"
    "Every tool takes a `profile` name. The first tool call for a profile lazily launches a "
    "dedicated browser with a persistent on-disk profile (cookies/storage survive restarts). "
    "Different profile names never share state; the same name is exclusive across OS "
    "processes.\n\n"
    "Typical workflow:\n"
    "1. `navigate(profile, url)` — starts the session on first use and loads a page.\n"
    "2. `snapshot(profile)` — get the UID (eN) tree of interactive elements.\n"
    "3. `click`/`fill`/`type_text`/... — act on elements by UID.\n"
    "4. Re-`snapshot` after each interaction; UIDs are invalidated by navigation.\n"
    "5. `close_session(profile)` when done (the profile stays on disk for reuse)."
)


def build_server(config: ServerConfig) -> FastMCP:
    """Compose the FastMCP server: dependencies, lifespan and tool registration."""
    sessions = SessionManager(config)
    telemetry = TelemetryLogger(config.logs_dir)
    deps = ToolDeps(config=config, sessions=sessions, telemetry=telemetry)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, object]]:
        await ensure_browser_present(config)
        refresh = schedule_refresh(config)
        try:
            yield {"config": config, "sessions": sessions, "telemetry": telemetry}
        finally:
            if refresh is not None:
                refresh.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresh
            await sessions.shutdown()

    mcp = FastMCP(name="Camoufox Browser", instructions=_INSTRUCTIONS, lifespan=lifespan)
    register_all_tools(mcp, deps)
    return mcp


def _configure_logging(config: ServerConfig) -> None:
    # stdio transport: logs MUST go to a file, never to stdout/stderr.
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    handler = logging.FileHandler(config.logs_dir / f"server-{stamp}.log", encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
    )


def main() -> None:
    config = ServerConfig.from_env()
    _configure_logging(config)
    build_server(config).run(transport="stdio")


if __name__ == "__main__":
    main()
