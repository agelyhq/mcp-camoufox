from __future__ import annotations

import functools
import inspect
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from camoufox_mcp.telemetry import UsageRecord, now_iso, truncate_args

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import FastMCP

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions import Page, Session, SessionManager
    from camoufox_mcp.telemetry import TelemetryLogger

logger = logging.getLogger(__name__)

_NOTE_MAX = 200


@dataclass(frozen=True)
class ToolDeps:
    """Dependency-injection bundle handed to every ``register(mcp, deps)``."""

    config: ServerConfig
    sessions: SessionManager
    telemetry: TelemetryLogger


async def get_session(deps: ToolDeps, profile: str, **init_opts: Any) -> Session:
    """Return (or lazily create) the session for ``profile``.

    ``init_opts`` are creation-only overrides: fingerprint_os, viewport_width,
    viewport_height, locale, block_images, block_webrtc. They are ignored when the
    profile is already active. May raise ``ProfileInUseError``.
    """
    return await deps.sessions.get_or_create(profile, **init_opts)


def get_page(session: Session) -> Page:
    """The session's active tab."""
    return session.active_page


def format_error(exc: BaseException) -> str:
    """Render an exception per the error contract ("Timeout: ..." / "Error: Type: msg")."""
    if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)):
        return f"Timeout: {exc}"
    return f"Error: {type(exc).__name__}: {exc}"


def tool(
    mcp: FastMCP, deps: ToolDeps, name: str | None = None
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Register an async handler as an MCP tool with telemetry + the error contract.

    The wrapped handler is timed, its call is written to telemetry once, and any
    exception is converted to the ``"Error: Type: message"`` string (timeouts to
    ``"Timeout: ..."``). Use as::

        @tool(mcp, deps)
        async def navigate(profile: str, url: str) -> str: ...
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        tool_name = name or fn.__name__
        return mcp.tool(_traced(deps, tool_name, fn))

    return decorator


def _traced(
    deps: ToolDeps, tool_name: str, fn: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        profile = _extract_profile(fn, args, kwargs)
        ok = True
        error: str | None = None
        note: str | None = None
        try:
            result = await fn(*args, **kwargs)
            note = _result_note(result)
            return result
        except (TimeoutError, PlaywrightTimeoutError) as exc:
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            note = f"Timeout: {exc}"
            return f"Timeout: {exc}"
        except Exception as exc:
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            note = f"Error: {type(exc).__name__}: {exc}"
            return f"Error: {type(exc).__name__}: {exc}"
        finally:
            deps.telemetry.log(
                UsageRecord(
                    ts=now_iso(),
                    profile=profile,
                    tool=tool_name,
                    args=truncate_args(kwargs),
                    duration_ms=round((time.perf_counter() - start) * 1000, 3),
                    ok=ok,
                    error=error,
                    result=note,
                )
            )

    return wrapper


def _extract_profile(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "profile" in kwargs:
        return kwargs["profile"]
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return bound.arguments.get("profile")
    except (TypeError, ValueError):
        return None


def _result_note(result: Any) -> str:
    if isinstance(result, str):
        return result[:_NOTE_MAX]
    return f"<{type(result).__name__}>"
