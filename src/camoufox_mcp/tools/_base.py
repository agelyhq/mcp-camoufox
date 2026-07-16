from __future__ import annotations

import functools
import inspect
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastmcp.utilities.types import Image

from camoufox_mcp.telemetry import (
    UsageRecord,
    estimate_image_tokens,
    now_iso,
    png_dimensions,
    truncate_args,
    truncate_note,
)
from camoufox_mcp.telemetry_intent import evaluate_analytics
from camoufox_mcp.tools._errors import error_detail, format_error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import FastMCP

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions import Page, Session, SessionManager
    from camoufox_mcp.telemetry import TelemetryLogger


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
        result: Any = None
        completed = False
        try:
            result = await fn(*args, **kwargs)
            completed = True
        except Exception as exc:
            completed = True
            ok = False
            error = error_detail(exc)
            result = format_error(exc)
        finally:
            if not completed:
                # Only a BaseException (asyncio.CancelledError, KeyboardInterrupt,
                # SystemExit) reaches here: the call was aborted, not a success.
                # Log it as a failure, then let the exception propagate untouched.
                ok = False
                error = "cancelled"
                result = None
            _log_record(deps, tool_name, profile, kwargs, start, ok, error, result)
        return result

    return wrapper


def _log_record(
    deps: ToolDeps,
    tool_name: str,
    profile: Any,
    kwargs: dict[str, Any],
    start: float,
    ok: bool,
    error: str | None,
    result: Any,
) -> None:
    extra: dict[str, Any] = {}
    if tool_name == "evaluate" and isinstance(kwargs.get("script"), str):
        extra = evaluate_analytics(kwargs["script"])
    deps.telemetry.log(
        UsageRecord(
            ts=now_iso(),
            profile=profile,
            tool=tool_name,
            args=truncate_args(kwargs),
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            ok=ok,
            error=error,
            url=_active_url(deps, profile),
            extra=extra,
            **_summarize_result(result),
        )
    )


def _summarize_result(result: Any) -> dict[str, Any]:
    """Build ``result``/``result_chars``/``img_*`` fields from a tool's return value.

    Handles a plain ``str``, an ``Image``, or a ``list`` mixing both (screenshot's
    downscale note + image): string parts feed ``result_chars`` and the note, image
    metadata comes from the first ``Image`` found.
    """
    str_parts, image = _split_result(result)
    fields: dict[str, Any] = {}
    note = ""
    if str_parts:
        fields["result_chars"] = sum(len(part) for part in str_parts)
        note = truncate_note("\n".join(str_parts))
    if image is not None:
        fields.update(_image_fields(image))
        note = f"{note} <Image>".strip() if note else "<Image>"
    elif not str_parts:
        note = f"<{type(result).__name__}>"
    fields["result"] = note
    return fields


def _split_result(result: Any) -> tuple[list[str], Image | None]:
    if isinstance(result, str):
        return [result], None
    if isinstance(result, Image):
        return [], result
    str_parts: list[str] = []
    image: Image | None = None
    if isinstance(result, (list, tuple)):
        for part in result:
            if isinstance(part, str):
                str_parts.append(part)
            elif isinstance(part, Image) and image is None:
                image = part
    return str_parts, image


def _image_fields(image: Image) -> dict[str, Any]:
    data = image.data
    if not data:
        return {}
    fields: dict[str, Any] = {"img_bytes": len(data)}
    dims = png_dimensions(data)
    if dims is not None:
        width, height = dims
        fields["img_w"] = width
        fields["img_h"] = height
        fields["est_image_tokens"] = estimate_image_tokens(width, height)
    return fields


def _active_url(deps: ToolDeps, profile: Any) -> str | None:
    """Best-effort active-page URL; never creates a session, swallows every error."""
    try:
        session = deps.sessions.get(profile)
        if session is None:
            return None
        return session.active_page.url
    except Exception:
        return None


def _extract_profile(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "profile" in kwargs:
        return kwargs["profile"]
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return bound.arguments.get("profile")
    except (TypeError, ValueError):
        return None
