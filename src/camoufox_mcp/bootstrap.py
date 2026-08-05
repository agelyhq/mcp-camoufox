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
    from collections.abc import AsyncIterator, Callable

    from camoufox_mcp.config import ServerConfig

SERVER_NAME = "Camoufox Browser"

# Everything true of every tool is stated here once instead of in 27 docstrings: the
# tool list is re-sent in full on every conversation, so doctrine repeated per tool is
# paid per tool. Only add a line here that changes what an agent does.
SERVER_INSTRUCTIONS = """\
Browser automation over Camoufox (anti-detect Firefox): 1 isolated browser per profile.

PROFILES
- Every tool but `list_sessions` takes `profile`. The first call for a name launches
  a browser with a persistent on-disk profile, so cookies and logins survive restarts.
- Use 1 profile for the whole conversation, named for the work ("invoice-audit"), not
  for the site. Names never share state.
- "ProfileInUseError: profile 'p' is locked by another process" means another process
  owns that browser. Pick a different name instead of retrying.
- `close_session(profile)` when finished. The profile stays on disk for reuse.

FINDING ELEMENTS
- `snapshot` returns a uid tree of what can be clicked or typed into, plus the
  ancestors placing it; `find` returns only the elements matching a role, name, text,
  label, placeholder, test id or CSS, for a fraction of the tokens. Prefer `find`
  when you know what you are looking for.
- A uid (`e12`) names 1 element in 1 tab and 1 document, not a position. It survives
  re-renders and further snapshots there, so reuse it. Navigating or switching tabs
  discards every uid you hold: snapshot again after either.
- "unknown or stale uid 'eN'; take a new snapshot" means that element is gone, or
  the uid belongs to another page; snapshot again.
- A `selector` is plain CSS plus `:has-text("...")` and `text=...`. The first visible
  match wins. Any other engine (xpath=, nth=, >>) raises, naming what is supported.

READING A PAGE
- Prefer `snapshot` and `find` over `screenshot`. An image costs about 1,000 tokens,
  carries no uid to act on, and cannot be searched. Screenshot only to judge layout,
  rendering or a picture.
- `get_element` reads 1 property of an element and `get_html(mode="text", selector=...)`
  reads the text of 1 region. Reach for `evaluate` only when no tool answers the
  question: it is the most expensive and most fragile option.

ACTING
- `click`, `click_at`, `fill` and `navigate` take `observe`: "none" (default),
  "snapshot" (fresh uid tree) or "text" (page text). Both save the follow-up read and
  both add up to 4000 chars to the result, truncated with a note when the page is
  bigger. That is the trade: keep observe="none" when you know what the action did.
- `click` and `fill` take exactly 1 of `uid` or `selector`.
- `new_page` opens a tab and `close_page` closes 1. Close tabs you are done with:
  an open tab keeps its memory, listeners and monitors alive all session.

ERRORS
- A failing tool returns 1 line, "Error: <Type>: <message>" or "Timeout: <message>",
  as its normal result. Nothing is raised, so read the returned string.
"""


def build_deps(config: ServerConfig) -> ToolDeps:
    """Build the injected tool dependencies (telemetry + session manager)."""
    telemetry = TelemetryLogger(config.logs_dir)
    sessions = SessionManager(config, on_closed=_session_closed_marker(telemetry))
    return ToolDeps(config=config, sessions=sessions, telemetry=telemetry)


def _session_closed_marker(telemetry: TelemetryLogger) -> Callable[[str, str], None]:
    """The observer the session manager notifies when a profile's browser is gone.

    The record is built here, next to ``server_start``, and not in the manager: the
    session layer owns when a browser dies, this file owns what the log says about
    it. ``TelemetryLogger.log`` is best-effort and never raises.
    """

    def on_closed(profile: str, reason: str) -> None:
        telemetry.log(
            UsageRecord(
                ts=now_iso(),
                profile=profile,
                tool="session_closed",
                args={"reason": reason},
                duration_ms=0.0,
                ok=True,
                error=None,
                result=None,
            )
        )

    return on_closed


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
    """Reduce a proxy config to ``scheme://host``: never log credentials or port."""
    if not proxy:
        return None
    parsed = urlparse(proxy.get("server", ""))
    if not parsed.hostname:
        return "REDACTED"
    return f"{parsed.scheme or 'http'}://{parsed.hostname}"
