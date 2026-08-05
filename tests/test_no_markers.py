"""The contract of the element-identity rewrite: the page cannot tell we were here.

One session arms the probes of :mod:`tests.probes` on an inert page and then drives every
uid-consuming path over it. Nothing may be written to the DOM, no branded event may be
dispatched, no observer may be constructed in the page realm, and no listener may appear
on window. A second test proves the probes themselves work, so a silently broken probe
cannot pass everything.

The claim is about what THIS server does. The 2 other actors that can reach the page, the
browser's own extension and the HTML parser, are dealt with where the probes are defined,
so a record read here is ours or it is the browser's and named as such. The one
driver-level artifact this server cannot prevent is pinned in
:mod:`tests.test_driver_footprint`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.helpers import PROFILE, evaluate, extract_uid, open_page, tool_text
from tests.probes import (
    INTERCEPTOR_EVENTS,
    arm_probes,
    probe_server,
    probes_after_the_leak_window,
    probes_when,
    touched,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client, FastMCP


@pytest.fixture
def mcp_server(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> FastMCP:
    return probe_server(monkeypatch, data_dir)


async def _drive_every_uid_path(client: Client, upload: str) -> None:
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


async def test_no_markers_on_any_uid_path(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    await open_page(client, f"{flask_server}/probe")
    await arm_probes(client)

    upload = tmp_path / "marker-free.txt"
    upload.write_bytes(b"marker free upload")
    await _drive_every_uid_path(client, str(upload))

    probes = await probes_after_the_leak_window(client)

    assert probes["marks"] == [], "a target-marking event reached the page"
    # The tallies below ride along: this assertion is the one that has fired on a runner,
    # and the 2 after it never got to say whether they were clean.
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
