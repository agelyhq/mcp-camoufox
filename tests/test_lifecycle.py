"""Nothing this server starts is left abandoned: not a handle, not a protocol reply.

Three defects with one shape. The element store dropped its handle on every
navigation without ever releasing it, so the release path was reachable only on a tab
that had not navigated since its last operation; it now retires the handle and drains
it under the lock every operation takes. An operation that ran out of budget left its
protocol reply live and unowned, and the driver discards a late answer only when the
reply future is cancelled, which it only does when the task that issued the call is
cancelled: every run of the waiting suite ended on "Future exception was never
retrieved", which is how a team learns to ignore warnings. And the last 2 files of the
injected bundle reached for globals by name at call time, so a page that replaced one
of them after our boot both observed and could break every fill, pick and upload.
"""

from __future__ import annotations

import asyncio
import gc
from typing import TYPE_CHECKING, Any

import pytest

from camoufox_mcp.dom.registry import ElementRegistry
from camoufox_mcp.sessions.errors import PLAYWRIGHT_TARGET_CLOSED_ERROR
from tests.helpers import PROFILE, evaluate, extract_uid, isolate_camoufox_env, tool_text

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client, FastMCP

    from camoufox_mcp.tools._base import ToolDeps

UNREAD = "never retrieved"


@pytest.fixture
def deps(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> ToolDeps:
    """The same dependencies the server runs on, reachable for the live session."""
    isolate_camoufox_env(monkeypatch, data_dir)

    from camoufox_mcp.bootstrap import build_deps
    from camoufox_mcp.config import ServerConfig

    return build_deps(ServerConfig.from_env())


@pytest.fixture
def mcp_server(deps: ToolDeps) -> FastMCP:
    from camoufox_mcp.bootstrap import build_server

    return build_server(deps.config, deps)


class _Handle:
    """One execution context's handle: answers a canned result, counts releases."""

    def __init__(self, answer: Any = None, *, dispose_error: BaseException | None = None) -> None:
        self._answer = answer if answer is not None else {"ok": True}
        self._dispose_error = dispose_error
        self.released = 0

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return self._answer

    async def dispose(self) -> None:
        self.released += 1
        if self._dispose_error is not None:
            raise self._dispose_error


class _Page:
    """An evaluatable page owning a real store, over scripted handles."""

    def __init__(self, *handles: _Handle) -> None:
        self._handles = list(handles)
        self.built = 0
        self.elements = ElementRegistry(self, target_closed=PLAYWRIGHT_TARGET_CLOSED_ERROR)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return None

    async def evaluate_handle(self, expression: str, arg: Any = None) -> _Handle:
        self.built += 1
        return self._handles.pop(0)


async def test_a_retired_handle_is_released_by_the_next_operation() -> None:
    """A navigation must not cost a handle: the store owns it until it is released."""
    first, second = _Handle(), _Handle()
    page = _Page(first, second)

    await page.elements.call("resolve", {"id": "e1"})
    page.elements.forget()
    assert first.released == 0, "forget() does I/O, and a page event cannot await"

    await page.elements.call("resolve", {"id": "e1"})

    assert first.released == 1
    assert second.released == 0
    assert page.built == 2


async def test_a_retired_handle_is_released_when_the_tab_closes() -> None:
    """The close is the last chance to release, and it must reach a retired handle."""
    handle = _Handle()
    page = _Page(handle)

    await page.elements.call("resolve", {"id": "e1"})
    page.elements.forget()
    await page.elements.dispose()

    assert handle.released == 1


async def test_a_release_never_fails_the_operation_that_triggers_it() -> None:
    """Releasing is best effort: the context it belonged to is usually already gone."""
    doomed = _Handle(dispose_error=PLAYWRIGHT_TARGET_CLOSED_ERROR())
    page = _Page(doomed, _Handle())

    await page.elements.call("resolve", {"id": "e1"})
    page.elements.forget()

    assert await page.elements.call("resolve", {"id": "e1"}) == {"ok": True}
    assert doomed.released == 1


async def test_a_release_is_never_handed_a_handle_still_in_use() -> None:
    """The drain runs under the store lock, so it cannot overtake a live operation."""
    started = asyncio.Event()
    finish = asyncio.Event()

    class _SlowHandle(_Handle):
        async def evaluate(self, expression: str, arg: Any = None) -> Any:
            started.set()
            await finish.wait()
            return {"ok": True}

    slow = _SlowHandle()
    page = _Page(slow, _Handle())

    inflight = asyncio.ensure_future(page.elements.call("resolve", {"id": "e1"}))
    await started.wait()

    page.elements.forget()
    queued = asyncio.ensure_future(page.elements.call("resolve", {"id": "e1"}))
    await asyncio.sleep(0.05)
    assert slow.released == 0, "the handle was released while an operation still held it"

    finish.set()
    await inflight
    await queued
    assert slow.released == 1


async def test_an_expired_operation_leaves_no_unread_error_behind(
    client: Client,
    flask_server: str,
    deps: ToolDeps,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A budget that expires must not leave the driver holding an answer for nobody.

    Asserted on captured output rather than on an instrumented loop, because the
    report is what actually costs the team: a line on a green run that everyone
    learns to scroll past.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    session = deps.sessions.get(PROFILE)
    assert session is not None

    with pytest.raises(TimeoutError):
        await session.active_page.elements.call(
            "evaluate", {"src": "() => new Promise(() => {})", "ids": []}, timeout=0.3
        )

    # The abandoned answer arrives only when the tab goes, and it is reported only
    # when the reply is collected, so both must happen before the assertion.
    await deps.sessions.close_session(PROFILE)
    await asyncio.sleep(0.5)
    gc.collect()

    assert UNREAD not in caplog.text, caplog.text
    assert UNREAD not in capfd.readouterr().err


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


async def test_a_tab_survives_the_navigations_that_retire_its_handles(
    client: Client, flask_server: str, capfd: pytest.CaptureFixture[str]
) -> None:
    """The release runs against a context a navigation already destroyed, and is silent."""
    for _ in range(3):
        await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
        snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
        uid = extract_uid(snap, "Click me")
        clicked = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
        assert clicked.startswith("Clicked <button>"), clicked

    assert "Error" not in capfd.readouterr().err
