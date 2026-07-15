from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client


def _read_last_record(log_file: Path) -> dict:
    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, f"telemetry log {log_file} is empty"
    return json.loads(lines[-1])


async def test_tool_call_appends_jsonl(client: Client, flask_server: str, data_dir: Path) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": "telem"})

    log_file = data_dir / "logs" / "telem.jsonl"
    assert log_file.exists(), "expected a per-profile telemetry log"

    record = _read_last_record(log_file)
    assert record["profile"] == "telem"
    assert record["tool"] == "navigate"
    assert isinstance(record["args"], dict)
    assert record["args"].get("url") == f"{flask_server}/"
    assert isinstance(record["duration_ms"], (int, float))
    assert record["duration_ms"] >= 0
    assert record["ok"] is True
    assert record["error"] is None
    assert isinstance(record["result"], str)
    assert record["result"]
    # ts must be an ISO-8601 UTC timestamp.
    assert record["ts"].endswith("+00:00") or record["ts"].endswith("Z")


async def test_error_call_is_logged(client: Client, data_dir: Path) -> None:
    await client.call_tool("navigate", {"url": "not-a-real-url", "profile": "telem_err"})

    record = _read_last_record(data_dir / "logs" / "telem_err.jsonl")
    assert record["tool"] == "navigate"
    assert record["ok"] is False
    assert record["error"] is not None


async def test_profileless_tool_logs_to_server_file(client: Client, data_dir: Path) -> None:
    await client.call_tool("list_sessions", {})

    record = _read_last_record(data_dir / "logs" / "_server.jsonl")
    assert record["tool"] == "list_sessions"
    assert record["profile"] is None
