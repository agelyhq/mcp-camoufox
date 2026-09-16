"""What the upload page echoes back, read as the verdict every upload test shares."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, goto_and_find, text_content, tool_text
from tests.waits import poll_until

if TYPE_CHECKING:
    from fastmcp import Client

# The node the basic upload page writes its echo into; the composer page has one per
# hidden input, named by the caller.
BASIC_OUTPUT = "file-basic-output"
# A payload small enough that its size is read at a glance in a failure message.
TEXT = b"plain words"

# What the echo node reads once the page's fetch resolved, either way.
SERVER_ANSWERED = "Server response"
UPLOAD_FAILED = "error"


async def input_uid(client: Client, flask_server: str) -> str:
    """The uid of the basic upload page's visible file input, after navigating there."""
    return await goto_and_find(client, f"{flask_server}/upload", PROFILE, "input:file")


async def assert_attached(
    client: Client, uid: str, typed: str, *, name: str, size: int, mime: str
) -> None:
    """``typed`` reaches the page as the ``File`` the confirmation line describes."""
    result = await upload(client, uid, typed)
    assert result == f"Uploaded {name} ({mime}, {size} bytes) to {uid}", result
    await assert_server_received(client, name=name, size=size, content_type=mime)


async def upload(client: Client, uid: str, file_path: str) -> str:
    """The text ``upload_file`` answers for ``file_path`` aimed at ``uid``."""
    return tool_text(
        await client.call_tool(
            "upload_file", {"profile": PROFILE, "uid": uid, "file_path": file_path}
        )
    )


async def upload_by_selector(client: Client, selector: str, file_path: str) -> str:
    """The text ``upload_file`` answers for ``file_path`` aimed at ``selector``."""
    return tool_text(
        await client.call_tool(
            "upload_file", {"profile": PROFILE, "selector": selector, "file_path": file_path}
        )
    )


async def assert_server_received(
    client: Client, *, name: str, size: int, content_type: str, output: str = BASIC_OUTPUT
) -> None:
    """The page echoes back what the server actually parsed out of the multipart body.

    The echo node is polled until the page's fetch resolved either way, so the verdict
    below reads a settled answer and an expiry fails on the last text seen. Checking
    `"server response" in out or "filename" in out` proved nothing: the server's JSON
    always carries a `filename` key whenever the page printed "Server response", so the
    second branch was dead and neither branch looked at the bytes.
    """
    out, _ = await poll_until(
        lambda: text_content(client, PROFILE, output),
        lambda text: SERVER_ANSWERED in text or UPLOAD_FAILED in text.lower(),
    )
    out = json.loads(out)
    prefix, _, body = out.partition("\n")
    assert prefix == "Server response:", out
    assert json.loads(body) == {"filename": name, "content_type": content_type, "size": size}
