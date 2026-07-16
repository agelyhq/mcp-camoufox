from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastmcp import FastMCP

from camoufox_mcp.sessions import SessionManager
from camoufox_mcp.telemetry import TelemetryLogger, UsageRecord, now_iso
from camoufox_mcp.tools import register_all_tools
from camoufox_mcp.tools._base import ToolDeps
from camoufox_mcp.updater import ensure_browser_present, schedule_refresh

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from camoufox_mcp.config import ServerConfig

SERVER_NAME = "Camoufox Browser"

SERVER_INSTRUCTIONS = (
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


def build_deps(config: ServerConfig) -> ToolDeps:
    """Build the injected tool dependencies (telemetry + session manager)."""
    telemetry = TelemetryLogger(config.logs_dir)
    sessions = SessionManager(config, telemetry=telemetry)
    return ToolDeps(config=config, sessions=sessions, telemetry=telemetry)


def build_server(config: ServerConfig, deps: ToolDeps | None = None) -> FastMCP:
    """Compose the FastMCP server: dependencies, lifespan and tool registration.

    ``deps`` may be supplied by the daemon so it can reach the shared
    :class:`SessionManager` for its /health route and idle-TTL watchdog; when
    omitted a fresh set is built (the default stdio path).
    """
    deps = deps or build_deps(config)
    sessions = deps.sessions
    telemetry = deps.telemetry

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, object]]:
        _log_server_start(config, telemetry)
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

    mcp = FastMCP(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS, lifespan=lifespan)
    register_all_tools(mcp, deps)
    return mcp


def _log_server_start(config: ServerConfig, telemetry: TelemetryLogger) -> None:
    """Write the ``server_start`` marker (config snapshot) to ``_server.jsonl``."""
    telemetry.log(
        UsageRecord(
            ts=now_iso(),
            profile=None,
            tool="server_start",
            args={
                "headless": config.headless,
                "data_dir": str(config.data_dir),
                "auto_update": config.auto_update,
                "addons": len(config.addon_urls),
                "proxy": _redact_proxy(config.proxy),
            },
            duration_ms=0.0,
            ok=True,
            error=None,
            result=None,
        )
    )


def _redact_proxy(proxy: dict[str, str] | None) -> str | None:
    """Reduce a proxy config to ``scheme://host`` — never log credentials or port."""
    if not proxy:
        return None
    parsed = urlparse(proxy.get("server", ""))
    if not parsed.hostname:
        return "REDACTED"
    return f"{parsed.scheme or 'http'}://{parsed.hostname}"
