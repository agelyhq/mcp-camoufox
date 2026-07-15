from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, goto_and_find, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# Poll the output node until the async fetch resolves, instead of a blind sleep.
POLL_OUTPUT_JS = """
(async () => {
    for (let i = 0; i < 40; i++) {
        const t = document.getElementById('file-basic-output').textContent;
        if (t.includes('Server response') || t.toLowerCase().includes('error')) return t;
        await new Promise(r => setTimeout(r, 200));
    }
    return document.getElementById('file-basic-output').textContent;
})()
"""


async def test_upload_file(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"test content for upload")
        tmp_path = f.name

    try:
        result = tool_text(
            await client.call_tool(
                "upload_file",
                {"profile": PROFILE, "uid": uid, "file_path": tmp_path},
            )
        )
        assert "uploaded" in result.lower()

        js = await evaluate(client, PROFILE, POLL_OUTPUT_JS)
        assert "server response" in js.lower() or "filename" in js.lower()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def test_upload_missing_file(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")

    result = tool_text(
        await client.call_tool(
            "upload_file",
            {"profile": PROFILE, "uid": uid, "file_path": "/tmp/nonexistent_file_12345.txt"},
        )
    )
    assert "error" in result.lower()
