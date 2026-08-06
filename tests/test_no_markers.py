"""The contract of the element-identity rewrite: the page cannot tell we were here.

One session arms the probes of :mod:`tests.probes` on an inert page and then drives every
path that reaches it: every uid-consuming one, and ``get_html``, which consumes none.
``get_html`` is here because it was the 1 tool injecting a script of its own instead of
going through the bundle, so neither guard test covered it and its clone-and-strip pass
was free to mutate whatever it liked. Nothing may be written to the DOM, no branded event
may be dispatched, no observer may be constructed in the page realm, and no listener may
appear on window. 2 controls answer the "compared with what?" question: 1 proves the
probes fire on each signal, the other that the extension reading below names an extension
when there is one, so neither a broken probe nor a blind reading can pass everything.

The claim is about what THIS server does, so the session runs with no extension at all:
this project's own default addon is dropped and Camoufox's bundled uBlock Origin is
excluded, and the browser's own records are read back to prove it rather than trusting the
setting. That leaves this server, the page's own script and the driver as the only things
able to write to the page: the HTML parser is kept out by arming the probes on a finished
document only, and the one driver-level artifact this server cannot prevent is pinned in
:mod:`tests.test_driver_footprint`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from tests.helpers import PROFILE, evaluate, extract_uid, open_page, tool_text
from tests.probes import (
    INTERCEPTOR_EVENTS,
    UBO_ID,
    arm_probes,
    extensions_after_closing,
    probe_server,
    probes_after_the_leak_window,
    probes_when,
    touched,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import FastMCP


# The probe page is deliberately free of any script, which leaves ``strip_scripts``
# nothing to strip and a strip of the LIVE tree indistinguishable from a correct one.
# This adds 1 empty, inert script element, and it is added BEFORE the probes are armed
# so the insertion is not itself a record: what the probes then have to stay silent
# about is the removal of it.
ADD_INERT_SCRIPT_JS = """
(() => {
  const inert = document.createElement('script');
  inert.id = 'probe-inert-script';
  document.body.appendChild(inert);
  return 1;
})()
"""


@pytest.fixture
def mcp_server(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> FastMCP:
    return probe_server(monkeypatch, data_dir)


async def _drive_every_page_path(client: Client, upload: str) -> None:
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
        # The 3 shapes of the one read that takes no uid. ``strip_scripts`` on is the
        # one that matters here: it clones the document element and removes nodes, and
        # the probes are watching ``documentElement`` for exactly that. A pass that
        # ever stripped the live tree instead of the copy would be recorded below as a
        # childList mutation naming the <script> it took away.
        ("get_html", {"profile": PROFILE, "max_chars": 0}),
        ("get_html", {"profile": PROFILE, "selector": "#probe-btn", "strip_scripts": False}),
        ("get_html", {"profile": PROFILE, "mode": "text"}),
    ]
    for name, args in calls:
        result = await client.call_tool(name, args)
        if name != "screenshot":
            text_result = tool_text(result)
            assert not text_result.startswith(("Error:", "Timeout:")), f"{name}: {text_result}"


async def test_no_markers_on_any_page_path(
    client: Client, tmp_path: Path, data_dir: Path, flask_server: str
) -> None:
    await open_page(client, f"{flask_server}/probe")
    assert await evaluate(client, PROFILE, ADD_INERT_SCRIPT_JS) == "1"
    await arm_probes(client)

    upload = tmp_path / "marker-free.txt"
    upload.write_bytes(b"marker free upload")
    await _drive_every_page_path(client, str(upload))

    probes = await probes_after_the_leak_window(client)

    assert probes["marks"] == [], "a target-marking event reached the page"
    # The tallies below ride along: this assertion is the one that has fired on a runner,
    # and the 2 after it never got to say whether they were clean. What it fired on then was
    # an extension's work, which is why the session now runs with none and the closing
    # assertion of this test measures that rather than trusting the setting that asks for it.
    assert probes["mutations"] == [], (
        f"the page recorded mutations: {probes['mutations']} "
        f"(mo={probes['mo']}, listeners={probes['listeners']})"
    )
    assert probes["mo"] == 0, "a MutationObserver was constructed in the page realm"
    assert not any("__playwright_global_listeners_check__" in t for t in probes["listeners"])
    assert all(t not in probes["listeners"] for t in INTERCEPTOR_EVENTS), probes["listeners"]

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

    # Last, because it ends the session that everything above measured: this is that very
    # browser saying which extensions it held, and every verdict above is about us only if
    # the answer is none.
    assert await extensions_after_closing(client, data_dir) == []


async def test_the_extension_measurement_detects_camoufoxs_own_addon(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, flask_server: str
) -> None:
    """Control for the reading above: with the setting on, the browser names uBlock Origin.

    An empty list is what the test above ends on, and an instrument that always answers
    empty would satisfy it forever. This launches the same server with Camoufox's bundled
    addon left in, changing nothing else, and the same reading has to name it.
    """
    server = probe_server(monkeypatch, data_dir, bundled_addons="true")
    async with Client(server) as control:
        await open_page(control, f"{flask_server}/probe")
        assert await extensions_after_closing(control, data_dir) == [UBO_ID]


async def test_probe_instruments_actually_detect(client: Client, flask_server: str) -> None:
    """Control: without this, a silently broken probe would pass every assertion."""
    await open_page(client, f"{flask_server}/probe")
    await arm_probes(client)

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

    probes = await probes_when(
        client,
        lambda p: (
            p["marks"] == ["mark"]
            and touched(p)
            and p["mo"] == 1
            and "pointerdown" in p["listeners"]
        ),
    )
    assert probes["marks"] == ["mark"]
    assert touched(probes), probes["mutations"]
    assert probes["mo"] == 1
    assert "pointerdown" in probes["listeners"]


async def test_no_dom_residue(client: Client, flask_server: str) -> None:
    """Nothing is written to the DOM, mid-session as well as after a capture."""
    await open_page(client, f"{flask_server}/probe")

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
