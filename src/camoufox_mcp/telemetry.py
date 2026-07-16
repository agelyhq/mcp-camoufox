from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from camoufox_mcp.config import ensure_private_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_STR = 200
_SERVER_LOG = "_server"

# Anthropic vision billing approximates image cost as (width*height)/750 tokens,
# capped at the per-image ceiling of 1568 tokens (~1.15 megapixels).
_IMAGE_TOKEN_DIVISOR = 750
_IMAGE_TOKEN_CAP = 1568

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class UsageRecord:
    """One tool invocation, serialized as a single JSONL line.

    ``result`` is the ≤200-char note; ``result_chars`` preserves the full
    pre-truncation length of string results (``None`` for images). The ``img_*``
    fields describe an image payload (screenshot); ``url`` is the profile's active
    URL at call time. ``extra`` carries tool-specific analytics (e.g. evaluate
    intent) that are merged flat into the JSON line and never appear on other tools.
    """

    ts: str
    profile: str | None
    tool: str
    args: dict[str, Any]
    duration_ms: float
    ok: bool
    error: str | None
    result: str | None
    result_chars: int | None = None
    url: str | None = None
    img_w: int | None = None
    img_h: int | None = None
    img_bytes: int | None = None
    est_image_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class TelemetryLogger:
    """Append-only per-profile JSONL usage logger. Best-effort: never raises."""

    def __init__(self, logs_dir: Path) -> None:
        self._dir = logs_dir

    def log(self, record: UsageRecord) -> None:
        try:
            ensure_private_dir(self._dir)
            name = f"{record.profile or _SERVER_LOG}.jsonl"
            payload = asdict(record)
            extra = payload.pop("extra", None) or {}
            payload.update(extra)  # flatten tool-specific analytics onto the line
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with (self._dir / name).open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            logger.debug("Telemetry write failed", exc_info=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate_str(text: str) -> str:
    """Cap a string at ``_MAX_STR``, suffixing the full pre-truncation length."""
    if len(text) > _MAX_STR:
        return text[:_MAX_STR] + f"...[{len(text)} chars]"
    return text


def truncate_note(text: str) -> str:
    """Cap a note at 200 chars, suffixing the full length like ``truncate_args``."""
    return _truncate_str(text)


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse (width, height) from a PNG's IHDR header; ``None`` if not a PNG.

    The IHDR chunk always follows the 8-byte signature: 4-byte length, the tag
    ``IHDR``, then width and height as big-endian uint32.
    """
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def estimate_image_tokens(width: int, height: int) -> int:
    """Approximate Anthropic vision token cost for a ``width by height`` image."""
    return min(math.ceil(width * height / _IMAGE_TOKEN_DIVISOR), _IMAGE_TOKEN_CAP)


def truncate_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Cap long strings, elide binary/file payloads, drop the injected Context."""
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key == "ctx" or type(value).__name__ == "Context":
            continue
        out[key] = _truncate_value(value)
    return out


def _truncate_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (list, tuple)):
        return [_truncate_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _truncate_value(v) for k, v in value.items()}
    return value
