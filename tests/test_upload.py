from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from camoufox_mcp.dom import MAX_UPLOAD_BYTES
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


async def test_upload_file(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")

    payload = b"test content for upload"
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(payload)
        tmp_path = f.name

    try:
        result = tool_text(
            await client.call_tool(
                "upload_file",
                {"profile": PROFILE, "uid": uid, "file_path": tmp_path},
            )
        )
        assert "uploaded" in result.lower()

        await _assert_server_received(
            client,
            name=Path(tmp_path).name,
            size=len(payload),
            content_type="text/plain",
        )
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


async def test_upload_via_label_trigger(client: Client, flask_server: str) -> None:
    """The uid may point at the <label> that controls the input, not the input itself."""
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "Choose a file")

    payload = b"through the label"
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(payload)
        tmp_path = handle.name

    try:
        result = tool_text(
            await client.call_tool(
                "upload_file", {"profile": PROFILE, "uid": uid, "file_path": tmp_path}
            )
        )
        assert "uploaded" in result.lower(), result
        await _assert_server_received(
            client,
            name=Path(tmp_path).name,
            size=len(payload),
            content_type="text/plain",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def test_upload_too_large(client: Client, flask_server: str) -> None:
    """The bytes cross the protocol, so a size ceiling exists where there was none."""
    uid = await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
        handle.write(b"0" * (MAX_UPLOAD_BYTES + 1))
        tmp_path = handle.name

    try:
        result = tool_text(
            await client.call_tool(
                "upload_file", {"profile": PROFILE, "uid": uid, "file_path": tmp_path}
            )
        )
        assert f"upload_file accepts at most {MAX_UPLOAD_BYTES} bytes" in result
    finally:
        Path(tmp_path).unlink(missing_ok=True)
