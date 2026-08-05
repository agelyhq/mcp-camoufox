"""The contract of the element-identity rewrite: the page cannot tell we were here.

One session arms four probes on an inert page and then drives every uid-consuming
path over it. Nothing may be written to the DOM, no branded event may be dispatched,
no observer may be constructed in the page realm, and no listener may appear on
window. A second test proves the probes themselves work, so a silently broken probe
cannot pass everything.

The claim is about what THIS server does, and one driver-level path sits outside it:
page script that logs a DOM node makes the driver instantiate its injected script in
that world, whether or not console output is captured here. That is not assumed, it
is measured and pinned by the last test in this module, so the boundary moves only
when someone notices.

The server here runs with no browser extension: the default cookie blocker writes a
class onto <html> of its own accord, and this module measures OUR footprint, not the
browser's.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.helpers import PROFILE, evaluate, extract_uid, isolate_camoufox_env, tool_text

if TYPE_CHECKING:
    from fastmcp import Client, FastMCP


@pytest.fixture
def mcp_server(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> FastMCP:
    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_ADDON_URLS="")

    from camoufox_mcp.bootstrap import build_server
    from camoufox_mcp.config import ServerConfig

    return build_server(ServerConfig.from_env())


# Armed AFTER navigation, so nothing it installs is wiped by a load. The test then
# performs no further navigation.
ARM_PROBES_JS = """
(() => {
  window.__p = { marks: [], attrs: [], listeners: [], mo: 0 };
  document.addEventListener('__playwright_mark_target__', () => window.__p.marks.push('mark'), true);
  document.addEventListener('__playwright_unmark_target__', () => window.__p.marks.push('unmark'), true);
  const OrigMO = window.MutationObserver;
  window.MutationObserver = function (cb) { window.__p.mo++; return new OrigMO(cb); };
  new OrigMO((records) => {
    records.forEach((r) => window.__p.attrs.push(r.type + ':' + (r.attributeName || '')));
  }).observe(document.documentElement, { attributes: true, childList: true, subtree: true });
  const add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    try { if (this === window) window.__p.listeners.push(String(type)); } catch (e) { /* ignore */ }
    return add.call(this, type, fn, opts);
  };
  return 1;
})()
"""

READ_PROBES_JS = "window.__p"

# The capture-phase pointer set a driver's injected script installs on window.
_INTERCEPTOR_EVENTS = ("pointerdown", "auxclick", "touchcancel")


async def _read_probes(client: Client) -> dict:
    # The injected-script leak lands asynchronously, so give it time to show up.
    await asyncio.sleep(0.8)
    return json.loads(await evaluate(client, PROFILE, READ_PROBES_JS))


async def _drive_every_uid_path(client: Client, flask_server: str, upload: str) -> None:
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    button = extract_uid(snap, "Probe button")
    text = extract_uid(snap, "Full name")
    select = extract_uid(snap, "Fruit choice")
    check = extract_uid(snap, "Accept terms")
    file_uid = extract_uid(snap, "Attachment")
    deep = extract_uid(snap, "Deep button")

    calls = [
        ("click", {"profile": PROFILE, "uid": button}),
        ("click", {"profile": PROFILE, "selector": "#probe-btn"}),
        ("fill", {"profile": PROFILE, "uid": text, "value": "Ada Lovelace"}),
        ("fill", {"profile": PROFILE, "selector": "#probe-email", "value": "ada@example.com"}),
        ("fill", {"profile": PROFILE, "uid": select, "value": "Cherry"}),
        ("fill", {"profile": PROFILE, "uid": check, "value": "true"}),
        ("upload_file", {"profile": PROFILE, "uid": file_uid, "file_path": upload}),
        ("screenshot", {"profile": PROFILE}),
        ("screenshot", {"profile": PROFILE, "full_page": True}),
        ("screenshot", {"profile": PROFILE, "uid": button}),
        ("scroll", {"profile": PROFILE, "uid": deep}),
        ("find", {"profile": PROFILE, "role": "button"}),
        ("get_element", {"profile": PROFILE, "uid": button}),
        ("evaluate", {"profile": PROFILE, "script": "(el) => el.tagName", "uids": [button]}),
        ("wait_for", {"profile": PROFILE, "condition": "selector", "selector": "#probe-btn"}),
        (
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "predicate",
                "expression": "document.readyState === 'complete'",
            },
        ),
    ]
    for name, args in calls:
        result = await client.call_tool(name, args)
        if name != "screenshot":
            text_result = tool_text(result)
            assert not text_result.startswith(("Error:", "Timeout:")), f"{name}: {text_result}"


async def test_no_markers_on_any_uid_path(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})
    assert await evaluate(client, PROFILE, ARM_PROBES_JS) == "1"

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(b"marker free upload")
        upload = handle.name
    try:
        await _drive_every_uid_path(client, flask_server, upload)
    finally:
        Path(upload).unlink(missing_ok=True)

    probes = await _read_probes(client)

    assert probes["marks"] == [], "a target-marking event reached the page"
    assert probes["attrs"] == [], f"the page recorded mutations: {probes['attrs']}"
    assert probes["mo"] == 0, "a MutationObserver was constructed in the page realm"
    assert not any("__playwright_global_listeners_check__" in t for t in probes["listeners"])
    assert all(t not in probes["listeners"] for t in _INTERCEPTOR_EVENTS), probes["listeners"]

    assert (
        await evaluate(client, PROFILE, "document.querySelectorAll('[data-mcp-uid]').length") == "0"
    )
    leaked = await evaluate(
        client,
        PROFILE,
        "Object.getOwnPropertyNames(window).filter(k => /playwright|inject|mcp/i.test(k)).length",
    )
    assert leaked == "0"
    assert await evaluate(client, PROFILE, "Object.getOwnPropertySymbols(window).length") == "0"


async def test_probe_instruments_actually_detect(client: Client, flask_server: str) -> None:
    """Control: without this, a silently broken probe would pass every assertion."""
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})
    assert await evaluate(client, PROFILE, ARM_PROBES_JS) == "1"

    await evaluate(
        client,
        PROFILE,
        "(() => {"
        "  const b = document.getElementById('probe-btn');"
        "  b.dispatchEvent(new CustomEvent('__playwright_mark_target__',"
        "    { bubbles: true, composed: true }));"
        "  b.setAttribute('data-touched', '1');"
        "  new MutationObserver(() => {}).observe(document.body, { childList: true });"
        "  window.addEventListener('pointerdown', () => {});"
        "  return 1;"
        "})()",
    )

    probes = await _read_probes(client)
    assert probes["marks"] == ["mark"]
    assert "attributes:data-touched" in probes["attrs"]
    assert probes["mo"] == 1
    assert "pointerdown" in probes["listeners"]


async def test_no_dom_residue(client: Client, flask_server: str) -> None:
    """Issue 7: nothing is written to the DOM, mid-session as well as after a capture."""
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})

    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    assert (
        await evaluate(client, PROFILE, "document.querySelectorAll('[data-mcp-uid]').length") == "0"
    )

    await client.call_tool("click", {"profile": PROFILE, "uid": extract_uid(snap, "Probe button")})
    tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    assert (
        await evaluate(client, PROFILE, "document.querySelectorAll('[data-mcp-uid]').length") == "0"
    )

    html = tool_text(await client.call_tool("get_html", {"profile": PROFILE}))
    assert "data-mcp-uid" not in html


LOG_STRING_JS = "(() => { console.log('plain string'); return 1; })()"
LOG_NODE_JS = "(() => { console.log(document.body); return 1; })()"


async def test_node_valued_console_argument_forces_the_driver_injected_script(
    client: Client, flask_server: str
) -> None:
    """The one page-visible artifact this server cannot prevent, pinned on purpose.

    When page script logs a DOM node, the Firefox driver builds an element handle for
    that argument inside its own console handler (coreBundle.js:43478 ``_onConsole``
    -> :42843 ``createHandle3`` -> :16039 the ``ElementHandle`` constructor), and the
    constructor evaluates the driver's injected script into the world the node lives
    in, which installs its branded listener set on window. The handles are built while
    calling ``addConsoleMessage`` (:19925), which only afterwards checks whether anyone
    subscribed, so dropping this server's console capture changes nothing. There is no
    supported client-side switch for it.

    Logging a string on the same page is the control, so neither half of this can pass
    by accident. If the node case ever stops leaking, this test fails: that is the
    signal to tighten the invariant above and the wording in the docs.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/probe", "profile": PROFILE})
    assert await evaluate(client, PROFILE, ARM_PROBES_JS) == "1"

    assert await evaluate(client, PROFILE, LOG_STRING_JS) == "1"
    control = await _read_probes(client)
    assert control["listeners"] == [], f"a string argument leaked: {control['listeners']}"
    assert control["mo"] == 0

    assert await evaluate(client, PROFILE, LOG_NODE_JS) == "1"
    probes = await _read_probes(client)
    assert any("__playwright_global_listeners_check__" in t for t in probes["listeners"]), (
        "the driver no longer instantiates its injected script for a node-valued "
        f"console argument: tighten the invariant and the docs. Got {probes['listeners']}"
    )
    assert all(t in probes["listeners"] for t in _INTERCEPTOR_EVENTS), probes["listeners"]
    assert probes["mo"] == 1, probes["mo"]
