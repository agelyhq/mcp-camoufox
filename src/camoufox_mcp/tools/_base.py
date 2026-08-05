from __future__ import annotations

import functools
import inspect
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from camoufox_mcp.tools._errors import error_detail, format_error, is_unexpected
from camoufox_mcp.tools._page_line import note_page, page_context_suffix
from camoufox_mcp.tools._settled_observation import settled_observation
from camoufox_mcp.tools._telemetry import log_record

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import FastMCP

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions import Page, Session, SessionInitOptions, SessionManager
    from camoufox_mcp.telemetry import TelemetryLogger

logger = logging.getLogger(__name__)

# The navigation budget every tool that drives one spends, stated once so the 4
# signatures cannot drift apart.
DEFAULT_TIMEOUT_MS = 30000


@dataclass(frozen=True)
class ToolDeps:
    """Dependency-injection bundle handed to every ``register(mcp, deps)``."""

    config: ServerConfig
    sessions: SessionManager
    telemetry: TelemetryLogger


async def get_session(
    deps: ToolDeps, profile: str, opts: SessionInitOptions | None = None
) -> Session:
    """Return (or lazily create) the session for ``profile``.

    ``opts`` is the resolved creation-time shape of the browser, built by the one
    tool that exposes those parameters; it is ignored when the profile is already
    active, and ``None`` means the server-wide defaults. May raise
    ``ProfileInUseError``.
    """
    return await deps.sessions.get_or_create(profile, opts)


def get_page(session: Session) -> Page:
    """The session's active tab."""
    return session.active_page


def tool(
    mcp: FastMCP,
    deps: ToolDeps,
    analytics: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Register an async handler as an MCP tool with telemetry + the error contract.

    The wrapped handler is timed, its call is written to telemetry once, and any
    exception is converted to the ``"Error: Type: message"`` string (timeouts to
    ``"Timeout: ..."``). Use as::

        @tool(mcp, deps)
        async def navigate(profile: str, url: str) -> str: ...

    ``analytics`` is the tool's own telemetry enrichment: a function of the bound
    arguments returning the extra fields its records carry. Declaring it here is what
    keeps the wrapper free of any knowledge of individual tools.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        return mcp.tool(_traced(deps, fn.__name__, fn, analytics))

    return decorator


def _traced(
    deps: ToolDeps,
    tool_name: str,
    fn: Callable[..., Awaitable[Any]],
    analytics: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        bound = _bind(fn, args, kwargs)
        profile = bound.get("profile")
        _seed_page_context(deps, tool_name, profile)
        ok = True
        error: str | None = None
        result: Any = None
        completed = False
        try:
            result = await fn(*args, **kwargs)
            completed = True
            result = await _decorate(deps, tool_name, profile, bound, result)
        except Exception as exc:
            completed = True
            ok = False
            error = error_detail(exc)
            result = format_error(exc)
            _log_unexpected(tool_name, profile, exc)
        finally:
            if not completed:
                # Only a BaseException (asyncio.CancelledError, KeyboardInterrupt,
                # SystemExit) reaches here: the call was aborted, not a success.
                # Log it as a failure, then let the exception propagate untouched.
                ok = False
                error = "cancelled"
                result = None
            log_record(
                deps.telemetry,
                tool=tool_name,
                profile=profile,
                args=bound,
                url=_active_url(deps, profile),
                start=start,
                ok=ok,
                error=error,
                result=result,
                extra=analytics(bound) if analytics else {},
            )
        return result

    return wrapper


def _seed_page_context(deps: ToolDeps, tool_name: str, profile: Any) -> None:
    """Record where the tab is, and what it had requested, before the tool runs."""
    page = _active_page(deps, profile)
    if page is not None:
        note_page(page, tool_name)


async def _decorate(
    deps: ToolDeps, tool_name: str, profile: Any, bound: dict[str, Any], result: Any
) -> Any:
    """Append the observation the call asked for, then the "[page] title | url" line.

    Both are wired here, once, rather than in each tool body: the wrapper already
    knows the tool's name and the arguments it was called with, so a body that
    restated either could drift from it. The order is fixed, because the page line
    is suppressed when the observation it follows already carries it.

    This sits between the body and the telemetry ``finally``, so ``result_chars``
    counts both suffixes; it is never reached on the error path, and a non-string
    result (screenshot's image) is passed through untouched.
    """
    if not isinstance(result, str):
        return result
    page = _active_page(deps, profile)
    if page is None:
        return result
    result += await settled_observation(page, tool_name, bound.get("observe"))
    return result + await page_context_suffix(page, tool_name, result, bound.get("url"))


def _log_unexpected(tool_name: str, profile: Any, exc: Exception) -> None:
    """Leave a full traceback in the server log for an off-contract exception.

    This is the single funnel every tool exception passes through, and the last
    place that still holds the live exception object: one line further down it has
    been folded to ``"Error: <Type>: <msg>"`` and the stack is gone for good. The
    tool result is untouched: the model still sees exactly one line.
    """
    if not is_unexpected(exc):
        return
    logger.error(
        "Unexpected %s in tool %r (profile=%r): %s",
        type(exc).__name__,
        tool_name,
        profile,
        exc,
        exc_info=exc,
    )


def _active_page(deps: ToolDeps, profile: Any) -> Page | None:
    """Best-effort active tab; never creates a session, swallows every error."""
    try:
        session = deps.sessions.get(profile)
        if session is None:
            return None
        return session.active_page
    except Exception:
        return None


def _active_url(deps: ToolDeps, profile: Any) -> str | None:
    """Best-effort active-page URL; never creates a session, swallows every error."""
    page = _active_page(deps, profile)
    return None if page is None else page.url


def _bind(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Every argument the call binds, by name, positional ones included.

    Binding once is what lets the wrapper read ``profile``, ``url`` and ``observe``
    without caring how they were passed, and what keeps the telemetry record from
    silently losing every argument of a positional call. Defaults are deliberately
    not filled in: the record is what the caller sent, not what the signature says.
    """
    try:
        return dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
    except (TypeError, ValueError):
        return dict(kwargs)
