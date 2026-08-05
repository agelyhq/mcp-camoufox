"""The injected bundle must never reach for a page global by name at call time.

The last 2 files of the bundle looked up ``Event``, ``File``, ``DataTransfer``,
``Uint8Array``, ``getSelection`` and ``createRange`` when an action ran, so a page that
replaced any of them after our boot both observed and could break every fill, pick and
upload. The bundle now captures them at boot; this test replaces them afterwards, which
is the only window that capture claims to cover, and drives every action that used them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, tool_text

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client

# One select, one rich field, one file input and one plain button, built after the
# load so the test owns every element it touches and depends on no template.
_BUILD_CONTROLS = """(() => {
  document.body.innerHTML =
    '<select id="pick" name="fruitpick">' +
    '<option value="a">Apple</option><option value="b">Banana</option></select>' +
    '<div id="note" contenteditable="true">Editable note</div>' +
    '<input id="doc" type="file" name="docupload">' +
    '<button id="go">Go now</button>';
  return document.body.children.length;
})()"""

# Replaced AFTER the store has booted, which is the only window the capture claims to
# cover. A thrower rather than a spy: it proves the calls do not go through these
# bindings at all, instead of counting how often they do.
_REPLACE_GLOBALS = """(() => {
  const boom = function () { throw new Error('replaced'); };
  window.Event = boom;
  window.File = boom;
  window.DataTransfer = boom;
  window.Uint8Array = boom;
  window.getSelection = boom;
  Document.prototype.createRange = boom;
  HTMLOptionsCollection.prototype[Symbol.iterator] = boom;
  return 'replaced';
})()"""


async def test_replacing_a_global_after_boot_cannot_reach_the_action_path(
    client: Client, flask_server: str, tmp_path: Path
) -> None:
    """Every action still works over a page that has replaced the globals it uses."""
    await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": PROFILE})
    assert await evaluate(client, PROFILE, _BUILD_CONTROLS) == "4"

    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    picker = extract_uid(snap, "fruitpick")
    note = extract_uid(snap, "Editable note")
    document_input = extract_uid(snap, "docupload")
    button = extract_uid(snap, "Go now")

    assert await evaluate(client, PROFILE, _REPLACE_GLOBALS) == '"replaced"'

    picked = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": picker, "value": "Banana"})
    )
    assert picked == "Selected 'Banana' in <select>", picked
    assert await evaluate(client, PROFILE, "document.getElementById('pick').value") == '"b"'

    typed = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": note, "value": "rewritten"})
    )
    assert typed.startswith("Filled <div>"), typed
    assert await evaluate(client, PROFILE, "document.getElementById('note').textContent") == (
        '"rewritten"'
    )

    upload = tmp_path / "note.txt"
    upload.write_text("hi", encoding="utf-8")
    attached = tool_text(
        await client.call_tool(
            "upload_file",
            {"profile": PROFILE, "uid": document_input, "file_path": str(upload)},
        )
    )
    assert attached.startswith("Uploaded "), attached
    assert await evaluate(client, PROFILE, "document.getElementById('doc').files[0].name") == (
        '"note.txt"'
    )

    scripted = tool_text(
        await client.call_tool(
            "evaluate",
            {"profile": PROFILE, "script": "(el) => el.id", "uids": [button]},
        )
    )
    assert scripted == '"go"', scripted
