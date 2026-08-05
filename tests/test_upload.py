from __future__ import annotations

import json
from typing import TYPE_CHECKING

from camoufox_mcp.dom import MAX_UPLOAD_BYTES
from tests.helpers import PROFILE, evaluate, goto_and_find, tool_text

if TYPE_CHECKING:
    from pathlib import Path

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


async def _assert_server_received(
    client: Client, *, name: str, size: int, content_type: str
) -> None:
    """The page echoes back what the server actually parsed out of the multipart body.

    Checking `"server response" in out or "filename" in out` proved nothing: the
    server's JSON always carries a `filename` key whenever the page printed "Server
    response", so the second branch was dead and neither branch looked at the bytes.
    """
    out = json.loads(await evaluate(client, PROFILE, POLL_OUTPUT_JS))
    prefix, _, body = out.partition("\n")
    assert prefix == "Server response:", out
    assert json.loads(body) == {"filename": name, "content_type": content_type, "size": size}


async def test_upload_file(client: Client, tmp_path: Path, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")

    payload = b"test content for upload"
    upload = tmp_path / "upload.txt"
    upload.write_bytes(payload)

    result = tool_text(
        await client.call_tool(
            "upload_file",
            {"profile": PROFILE, "uid": uid, "file_path": str(upload)},
        )
    )
    assert "uploaded" in result.lower()

    await _assert_server_received(
        client, name=upload.name, size=len(payload), content_type="text/plain"
    )


async def test_upload_missing_file(client: Client, tmp_path: Path, flask_server: str) -> None:
    """The path is named back, so the caller can see which one it got wrong."""
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")
    absent = tmp_path / "nowhere.txt"

    result = tool_text(
        await client.call_tool(
            "upload_file",
            {"profile": PROFILE, "uid": uid, "file_path": str(absent)},
        )
    )
    assert result == f"Error: ValueError: '{absent}' is not a readable file", result


async def test_upload_via_label_trigger(client: Client, tmp_path: Path, flask_server: str) -> None:
    """The uid may point at the <label> that controls the input, not the input itself."""
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "Choose a file")

    payload = b"through the label"
    upload = tmp_path / "labelled.txt"
    upload.write_bytes(payload)

    result = tool_text(
        await client.call_tool(
            "upload_file", {"profile": PROFILE, "uid": uid, "file_path": str(upload)}
        )
    )
    assert "uploaded" in result.lower(), result
    await _assert_server_received(
        client, name=upload.name, size=len(payload), content_type="text/plain"
    )


async def test_upload_too_large(client: Client, tmp_path: Path, flask_server: str) -> None:
    """The bytes cross the protocol, so a size ceiling exists where there was none."""
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")

    oversized = tmp_path / "oversized.bin"
    oversized.write_bytes(b"0" * (MAX_UPLOAD_BYTES + 1))

    result = tool_text(
        await client.call_tool(
            "upload_file", {"profile": PROFILE, "uid": uid, "file_path": str(oversized)}
        )
    )
    assert f"upload_file accepts at most {MAX_UPLOAD_BYTES} bytes" in result
