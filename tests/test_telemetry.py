from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from fastmcp import Client

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import FastMCP


def _read_records(log_file: Path) -> list[dict]:
    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _read_last_record(log_file: Path) -> dict:
    records = _read_records(log_file)
    assert records, f"telemetry log {log_file} is empty"
    return records[-1]


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
    # A profile-less tool cannot resolve an active page, so the url is null.
    assert record["url"] is None


async def test_success_and_intent_enrichment(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """One session exercises result_chars/url, evaluate intent, and error collapse."""
    profile = "enrich"
    await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": profile})
    read_script = "document.querySelector('h1').textContent"
    await client.call_tool("evaluate", {"profile": profile, "script": read_script})
    await client.call_tool(
        "evaluate", {"profile": profile, "script": "document.querySelector('#nope').click()"}
    )
    await client.call_tool("navigate", {"url": "not-a-real-url", "profile": profile})

    records = _read_records(data_dir / "logs" / f"{profile}.jsonl")
    navs = [r for r in records if r["tool"] == "navigate"]
    evals = [r for r in records if r["tool"] == "evaluate"]

    # --- Item 3 (result_chars) + Item 12 (url) on a successful call ---
    nav_ok = navs[0]
    assert nav_ok["ok"] is True
    assert isinstance(nav_ok["result_chars"], int)
    assert nav_ok["result_chars"] == len(nav_ok["result"])  # short result is not truncated
    assert isinstance(nav_ok["url"], str) and nav_ok["url"].startswith("http")
    # Item 11 fields are evaluate-only and must never appear on other tools.
    assert "intent" not in nav_ok
    assert "script_hash" not in nav_ok
    assert "script_len" not in nav_ok

    # --- Item 11 (evaluate intent analytics) ---
    read_rec = evals[0]
    assert read_rec["intent"] == "read"
    assert isinstance(read_rec["script_hash"], str) and len(read_rec["script_hash"]) == 12
    assert read_rec["script_len"] == len(read_script)
    assert isinstance(read_rec["url"], str) and read_rec["url"].startswith("http")
    # Intent is derived from the script even when the call fails (click checked
    # before read despite the querySelector, proving first-match ordering).
    click_rec = evals[1]
    assert click_rec["intent"] == "click"
    assert click_rec["ok"] is False

    # --- Item 2 (error rendering) on the failed navigation ---
    nav_err = navs[1]
    assert nav_err["ok"] is False
    note = nav_err["result"]
    assert "\n" not in note
    assert "Call log:" not in note
    assert "Error: Error:" not in note
    # The type slot after "Error: " is never the bare "Error" class name.
    match = re.match(r"Error: (\w+): ", note)
    assert match is not None and match.group(1) != "Error"
    assert len(note) <= 220  # 200-char cap + "...[N chars]" suffix
    assert isinstance(nav_err["result_chars"], int)
    assert nav_err["error"] is not None and "\n" not in nav_err["error"]
    assert "Call log:" not in nav_err["error"]


async def test_server_start_marker(client: Client, data_dir: Path) -> None:
    """Entering the client runs the lifespan, which logs the server_start marker."""
    records = _read_records(data_dir / "logs" / "_server.jsonl")
    starts = [r for r in records if r["tool"] == "server_start"]
    assert len(starts) == 1
    marker = starts[0]
    assert marker["profile"] is None
    assert marker["ok"] is True
    args = marker["args"]
    for key in ("headless", "data_dir", "auto_update", "addons", "proxy"):
        assert key in args, f"server_start args missing {key}"
    assert args["proxy"] is None  # no proxy configured in the test env
    # Credentials must never be serialized anywhere in the snapshot.
    dumped = json.dumps(args)
    assert "username" not in dumped and "password" not in dumped


async def test_session_closed_on_shutdown(
    mcp_server: FastMCP, flask_server: str, data_dir: Path
) -> None:
    """Closing the client context runs SessionManager.shutdown(), emitting a marker."""
    async with Client(mcp_server) as c:
        await c.call_tool("navigate", {"url": f"{flask_server}/", "profile": "closer"})

    records = _read_records(data_dir / "logs" / "closer.jsonl")
    closed = [r for r in records if r["tool"] == "session_closed"]
    assert len(closed) == 1
    marker = closed[0]
    assert marker["profile"] == "closer"
    assert marker["ok"] is True
    assert marker["args"] == {"reason": "shutdown"}


async def test_screenshot_image_metrics(client: Client, flask_server: str, data_dir: Path) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": "shot"})
    await client.call_tool("screenshot", {"profile": "shot"})

    record = _read_last_record(data_dir / "logs" / "shot.jsonl")
    assert record["tool"] == "screenshot"
    assert record["ok"] is True
    assert isinstance(record["img_w"], int) and record["img_w"] > 0
    assert isinstance(record["img_h"], int) and record["img_h"] > 0
    assert isinstance(record["img_bytes"], int) and record["img_bytes"] > 100
    assert isinstance(record["est_image_tokens"], int)
    assert 0 < record["est_image_tokens"] <= 1568
    # An image-only result carries no character count and a placeholder note.
    assert record["result_chars"] is None
    assert record["result"] == "<Image>"
