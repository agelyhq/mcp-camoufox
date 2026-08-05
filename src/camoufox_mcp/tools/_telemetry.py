"""Turning one finished tool call into one telemetry record.

Everything here is about what a call is worth measuring for; the decorator that
drives it lives in ``_base``. A tool never calls this: the ``@tool`` wrapper does,
exactly once per call, on the success and the failure path alike.
"""

from __future__ import annotations

import time
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

if TYPE_CHECKING:
    from camoufox_mcp.telemetry import TelemetryLogger


def log_record(
    telemetry: TelemetryLogger,
    *,
    tool: str,
    profile: Any,
    args: dict[str, Any],
    url: str | None,
    start: float,
    ok: bool,
    error: str | None,
    result: Any,
    extra: dict[str, Any],
) -> None:
    """Write the one line this call is owed.

    ``args`` is every argument the call actually bound, positional ones included;
    ``extra`` is whatever the tool's own analytics hook added, empty for the tools
    that declared none.
    """
    telemetry.log(
        UsageRecord(
            ts=now_iso(),
            profile=profile,
            tool=tool,
            args=truncate_args(args),
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            ok=ok,
            error=error,
            url=url,
            extra=extra,
            **summarize_result(result),
        )
    )


def summarize_result(result: Any) -> dict[str, Any]:
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
