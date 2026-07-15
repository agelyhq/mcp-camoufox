from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_STR = 200
_SERVER_LOG = "_server"


@dataclass(frozen=True)
class UsageRecord:
    """One tool invocation, serialized as a single JSONL line."""

    ts: str
    profile: str | None
    tool: str
    args: dict[str, Any]
    duration_ms: float
    ok: bool
    error: str | None
    result: str | None


class TelemetryLogger:
    """Append-only per-profile JSONL usage logger. Best-effort: never raises."""

    def __init__(self, logs_dir: Path) -> None:
        self._dir = logs_dir

    def log(self, record: UsageRecord) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            name = f"{record.profile or _SERVER_LOG}.jsonl"
            line = json.dumps(asdict(record), ensure_ascii=False, default=str)
            with (self._dir / name).open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            logger.debug("Telemetry write failed", exc_info=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
        if len(value) > _MAX_STR:
            return value[:_MAX_STR] + f"...[{len(value)} chars]"
        return value
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (list, tuple)):
        return [_truncate_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _truncate_value(v) for k, v in value.items()}
    return value
