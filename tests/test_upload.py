from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.dom import MAX_UPLOAD_BYTES
from tests.helpers import PROFILE, goto_and_find, text_content, tool_text
from tests.upload_helpers import assert_server_received, upload_by_selector
from tests.waits import poll_until

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client

# The confirmation names what the page's File was built with, then the uid it went to.
UPLOADED_LINE = re.compile(
    r"^Uploaded (?P<name>\S+) \((?P<mime>[^,]+), (?P<size>\d+) bytes\) to e\d+$"
)

# The mode the session runs in: ``isolate_camoufox_env`` keeps an ambient value and
# defaults to "true", the one mode where a native chooser attempt opens nothing.
HEADLESS_MODE = os.environ.get("CAMOUFOX_HEADLESS") or "true"
# What the composer page writes when its button ran ``input.click()``.
CHOOSER_LOG = "add-media clicked, input.click() dispatched"

NO_FILE_INPUT = (
    "Error: ValueError: no file input found for uid '{uid}'; pass "
    'selector="input[type=file]" (a hidden input is accepted) or the uid of the '
    "input's <label>"
)
EXACTLY_ONE = "Error: ValueError: provide exactly one of uid or selector"


def _assert_uploaded(result: str, name: str, mime: str, size: int) -> None:
    match = UPLOADED_LINE.match(result)
    assert match, result
    assert (match["name"], match["mime"], int(match["size"])) == (name, mime, size), result


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
    _assert_uploaded(result, upload.name, "text/plain", len(payload))

    await assert_server_received(
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
    assert result == (
        f"Error: ValueError: cannot read '{absent}': No such file or directory (errno 2)"
    ), result


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
    _assert_uploaded(result, upload.name, "text/plain", len(payload))
    await assert_server_received(
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


async def test_upload_reaches_a_hidden_input_by_selector(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """The composer's input is display:none, so it has no uid; the selector still binds it.

    ``input[type=file]`` is what the instructions tell an agent to pass, and on this
    page its first match is the hidden one: the same call that used to say "no element
    matches" now uploads, and the echo proves the page received name, type and size.
    """
    await goto_and_find(client, f"{flask_server}/composer", PROFILE, "Add media")
    payload = b"a post image, allegedly"
    upload = tmp_path / "post.txt"
    upload.write_bytes(payload)

    result = await upload_by_selector(client, "input[type=file]", str(upload))
    _assert_uploaded(result, upload.name, "text/plain", len(payload))
    await assert_server_received(
        client,
        name=upload.name,
        size=len(payload),
        content_type="text/plain",
        output="media-output",
    )


async def test_upload_reaches_a_transparent_and_a_form_wrapped_input(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """The 2 other shapes a site hides an input in: opacity:0 and inside a <form>."""
    await goto_and_find(client, f"{flask_server}/composer", PROFILE, "Attach")
    payload = b"through a transparent input"
    upload = tmp_path / "clear.txt"
    upload.write_bytes(payload)

    result = await upload_by_selector(client, "#clear-input", str(upload))
    _assert_uploaded(result, upload.name, "text/plain", len(payload))
    await assert_server_received(
        client,
        name=upload.name,
        size=len(payload),
        content_type="text/plain",
        output="clear-output",
    )

    result = await upload_by_selector(client, "#photo-form input[type=file]", str(upload))
    _assert_uploaded(result, upload.name, "text/plain", len(payload))
    await assert_server_received(
        client,
        name=upload.name,
        size=len(payload),
        content_type="text/plain",
        output="photo-output",
    )


@pytest.mark.skipif(
    HEADLESS_MODE != "true",
    reason="a native chooser attempt opens a real dialog on the desktop outside headless",
)
async def test_clicking_the_media_button_then_uploading_by_selector(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """The recovery path the instructions describe, proved on the tab it happens on.

    No tool intercepts the chooser a site's button opens (docs/decisions.md), so an
    agent that clicks "Add media" anyway must find the tab still answering: in
    headless the native picker is a silent no-op, the page's own handler ran, and
    ``upload_file`` by selector then attaches to the same hidden input. Twice, because
    the diagnosis measured that a chooser attempt changes what a later subscription
    would see; nothing here may depend on being the first attempt.
    """
    button = await goto_and_find(client, f"{flask_server}/composer", PROFILE, "Add media")
    payload = b"after a chooser attempt"
    upload = tmp_path / "post.txt"
    upload.write_bytes(payload)

    for _attempt in range(2):
        clicked = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": button}))
        assert clicked.startswith("Clicked <button> at ("), clicked
        log, seen = await poll_until(
            lambda: text_content(client, PROFILE, "click-log"),
            lambda t: t == json.dumps(CHOOSER_LOG),
        )
        assert seen, log

        result = await upload_by_selector(client, "input[type=file]", str(upload))
        _assert_uploaded(result, upload.name, "text/plain", len(payload))
        await assert_server_received(
            client,
            name=upload.name,
            size=len(payload),
            content_type="text/plain",
            output="media-output",
        )


async def test_upload_aimed_at_the_button_names_the_selector_route(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """The only uid the agent can get is the button's; the answer says what to pass instead."""
    button = await goto_and_find(client, f"{flask_server}/composer", PROFILE, "Add media")
    upload = tmp_path / "post.txt"
    upload.write_bytes(b"x")

    result = tool_text(
        await client.call_tool(
            "upload_file", {"profile": PROFILE, "uid": button, "file_path": str(upload)}
        )
    )
    assert result == NO_FILE_INPUT.format(uid=button), result


async def test_upload_takes_exactly_one_address(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """Both addresses and neither are refused with the wording every other tool uses."""
    button = await goto_and_find(client, f"{flask_server}/composer", PROFILE, "Add media")
    upload = tmp_path / "post.txt"
    upload.write_bytes(b"x")

    both = tool_text(
        await client.call_tool(
            "upload_file",
            {
                "profile": PROFILE,
                "uid": button,
                "selector": "input[type=file]",
                "file_path": str(upload),
            },
        )
    )
    assert both == EXACTLY_ONE, both
    neither = tool_text(
        await client.call_tool("upload_file", {"profile": PROFILE, "file_path": str(upload)})
    )
    assert neither == EXACTLY_ONE, neither
