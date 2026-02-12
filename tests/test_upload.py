from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastmcp import Client  # noqa: TC002

from tests.helpers import extract_uid, tool_text


async def test_upload_file(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/upload"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "input:file")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"test content for upload")
        tmp_path = f.name

    try:
        result = tool_text(
            await client.call_tool(
                "upload_file",
                {"uid": uid, "file_path": tmp_path},
            )
        )
        assert "uploaded" in result.lower()
        await asyncio.sleep(2)

        js = tool_text(
            await client.call_tool(
                "evaluate",
                {"script": "document.getElementById('file-basic-output').textContent"},
            )
        )
        assert "server response" in js.lower() or "filename" in js.lower()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def test_upload_missing_file(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/upload"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "input:file")

    result = tool_text(
        await client.call_tool(
            "upload_file",
            {"uid": uid, "file_path": "/tmp/nonexistent_file_12345.txt"},
        )
    )
    assert "error" in result.lower()
