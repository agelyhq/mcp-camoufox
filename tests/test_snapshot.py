from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# 2000 buttons in a body of their own, so the record count is exactly the button count.
FILL_BODY_JS = (
    "(() => { const p = []; for (let i = 0; i < 2000; i++) "
    "{ p.push('<button>Btn ' + i + '</button>'); } "
    "document.body.innerHTML = p.join(''); return p.length; })()"
)


async def _snapshot(client: Client, **kwargs: object) -> str:
    return tool_text(await client.call_tool("snapshot", {"profile": PROFILE, **kwargs}))


async def _open(client: Client, flask_server: str, path: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}{path}", "profile": PROFILE})


def _uids(text: str) -> list[str]:
    return re.findall(r"e\d+", text)


def _lines_with(snap: str, needle: str) -> list[str]:
    return [line for line in snap.splitlines() if needle in line]


def _line_with(snap: str, needle: str) -> str:
    lines = _lines_with(snap, needle)
    assert len(lines) == 1, f"expected exactly 1 line holding {needle!r}, got {lines}"
    return lines[0]


def _button_numbers(snap: str) -> list[int]:
    return [int(n) for n in re.findall(r"Btn (\d+)", snap)]


async def test_snapshot_returns_tree(client: Client, flask_server: str) -> None:
    await _open(client, flask_server, "/snapshot")

    snap = await _snapshot(client)
    # Count the eNN UIDs instead of substring-matching "e0"/"e1" (which also
    # matches "e10", "e11", ...). The rich snapshot page has many UIDs.
    assert len(_uids(snap)) >= 5
    assert "heading" in snap.lower() or "button" in snap.lower() or "link" in snap.lower()


async def test_snapshot_contains_uids(client: Client, flask_server: str) -> None:
    await _open(client, flask_server, "/click")

    snap = await _snapshot(client)
    assert "Click me" in snap
    assert "Double-click" in snap

    assert len(_uids(snap)) >= 3


async def test_snapshot_lazily_creates_session(client: Client, flask_server: str) -> None:
    """`snapshot` on an unused profile launches the session on a blank page."""
    snap = tool_text(await client.call_tool("snapshot", {"profile": "fresh_snap"}))
    assert "error" not in snap.lower()


async def test_snapshot_max_nodes_truncates(client: Client, flask_server: str) -> None:
    """A DOM larger than max_nodes is capped and reports the overflow count."""
    await _open(client, flask_server, "/snapshot")
    await evaluate(client, PROFILE, FILL_BODY_JS)

    snap = await _snapshot(client)  # default max_nodes=1500

    assert "[truncated: 500 more nodes" in snap
    # The hint no longer offers interactive_only, which is already on by default.
    assert "interactive_only" not in snap
    # A uid names an element, not a position, so the kept prefix is identified by its
    # CONTENT and the uids only have to be an injective naming of it.
    uids = _uids(snap)
    assert len(uids) == 1500
    assert len(set(uids)) == 1500
    assert _button_numbers(snap) == list(range(1500))


async def test_snapshot_max_nodes_raise_shows_all(client: Client, flask_server: str) -> None:
    """Raising max_nodes above the node count renders the whole tree, no note."""
    await _open(client, flask_server, "/snapshot")
    await evaluate(client, PROFILE, FILL_BODY_JS)

    snap = await _snapshot(client, max_nodes=2500)

    assert "truncated" not in snap
    uids = _uids(snap)
    assert len(uids) == len(set(uids)) == 2000
    assert _button_numbers(snap) == list(range(2000))


async def test_snapshot_defaults_to_interactive_only(client: Client, flask_server: str) -> None:
    """The default serves the common case: what can be clicked or typed into."""
    await _open(client, flask_server, "/snapshot-names")

    lean = await _snapshot(client)
    full = await _snapshot(client, interactive_only=False)

    assert "Agree to terms" in lean
    assert "Send" in lean
    # A heading and a table with nothing to do in them are structure, not targets.
    assert "Data table" not in lean
    assert "Alpha value" not in lean
    assert "Data table" in full
    assert "Alpha value" in full
    assert len(lean) < len(full)


async def test_snapshot_interactive_only_drops_structural(
    client: Client, flask_server: str
) -> None:
    """interactive_only removes structural leaves but keeps every uid intact."""
    await _open(client, flask_server, "/snapshot")
    await evaluate(
        client,
        PROFILE,
        "(() => { const p = []; for (let i = 0; i < 40; i++) "
        "{ p.push('<p>Paragraph ' + i + '</p>'); } "
        "for (let i = 0; i < 5; i++) { p.push('<button>Action ' + i + '</button>'); } "
        "document.body.innerHTML = p.join(''); return p.length; })()",
    )

    full = await _snapshot(client, interactive_only=False)
    assert full.count("Paragraph") == 40
    assert "Action 0" in full

    lean = await _snapshot(client)
    assert "Paragraph" not in lean
    assert "Action 0" in lean
    assert len(_uids(lean)) == 5
    # The button uids are the same interactive elements in both renderings.
    assert extract_uid(full, "Action 0") == extract_uid(lean, "Action 0")


async def test_snapshot_interactive_only_keeps_ancestors(client: Client, flask_server: str) -> None:
    """A structural ancestor of an interactive element survives interactive_only."""
    await _open(client, flask_server, "/snapshot")
    await evaluate(
        client,
        PROFILE,
        "(() => { document.body.innerHTML = "
        "'<p>lonely para</p><form><label>Full name</label>"
        '<input type="text" name="fn"></form>\'; return 1; })()',
    )

    lean = await _snapshot(client, interactive_only=True)

    assert "lonely para" not in lean  # structural leaf dropped
    assert "form" in lean  # interactive ancestor kept for context
    assert "input:text" in lean


async def test_snapshot_keeps_uids_across_captures(client: Client, flask_server: str) -> None:
    """Two captures of the same document agree on every uid they both contain."""
    await _open(client, flask_server, "/click")

    first = await _snapshot(client)
    second = await _snapshot(client)

    for label in ("Click me", "Double-click me", "Count clicks"):
        assert extract_uid(first, label) == extract_uid(second, label), label


async def test_snapshot_pointer_grid_yields_one_uid_per_region(
    client: Client, flask_server: str
) -> None:
    """`cursor: pointer` inherits, so only the outermost node of a region is a target."""
    await _open(client, flask_server, "/snapshot-cards")

    snap = await _snapshot(client)

    for card in ("Card alpha", "Card beta", "Card gamma"):
        line = _line_with(snap, card)
        assert len(_uids(line)) == 1, line
    # 4 pointer regions, 1 real button inside the fourth, and the shared nav link.
    assert len(_uids(snap)) == 6, snap


async def test_snapshot_pointer_region_keeps_a_real_control(
    client: Client, flask_server: str
) -> None:
    """A control inside a pointer region brings a signal the cursor does not."""
    await _open(client, flask_server, "/snapshot-cards")

    snap = await _snapshot(client)

    assert re.search(r"\[button e\d+\] Card action", snap), snap
    assert extract_uid(snap, "Card action") not in _uids(_line_with(snap, "Card alpha"))


async def test_snapshot_styled_checkbox_is_targetable(client: Client, flask_server: str) -> None:
    """A <label> around a hidden input carries the uid, the role and the state."""
    await _open(client, flask_server, "/snapshot-names")

    snap = await _snapshot(client)
    line = _line_with(snap, "Agree to terms")
    assert "(control=checkbox, name=agree, unchecked)" in line, line

    uid = extract_uid(snap, "Agree to terms")
    clicked = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert clicked.startswith("Clicked <label>"), clicked

    # The page's own handler ran, so the click reached the input and did not merely
    # repaint the label.
    assert json.loads(await text_content(client, PROFILE, "agree-output")) == "on"
    after = _line_with(await _snapshot(client), "Agree to terms")
    assert "(control=checkbox, name=agree, checked)" in after, after


async def test_snapshot_hidden_control_alone_makes_the_label_a_target(
    client: Client, flask_server: str
) -> None:
    """No pointer cursor, no role, no handler: the hidden control is the only signal."""
    await _open(client, flask_server, "/snapshot-names")

    line = _line_with(await _snapshot(client), "Fast shipping")

    assert re.fullmatch(
        r"\s*\[label e\d+\] Fast shipping \(control=radio, name=shipping, checked\)", line
    ), line


async def test_snapshot_select_name_excludes_its_options(client: Client, flask_server: str) -> None:
    """A control's options are its data: concatenating them names nothing."""
    await _open(client, flask_server, "/snapshot-names")

    snap = await _snapshot(client)

    assert "AppleBerry" not in snap
    line = _line_with(snap, "name=fruit")
    assert re.fullmatch(r"\s*\[select e\d+\] \(name=fruit, value=a, Apple\)", line), line
    # Same class of bug, other containers: a datalist lends nothing to its input.
    assert "ReddishGreenish" not in snap


async def test_snapshot_button_name_comes_from_its_nested_span(
    client: Client, flask_server: str
) -> None:
    """<button><span>Send</span></button> has no direct text child, and still a name."""
    await _open(client, flask_server, "/snapshot-names")

    snap = await _snapshot(client)

    assert re.search(r"\[button e\d+\] Send$", snap, re.MULTILINE), snap


async def test_snapshot_nested_text_is_printed_once(client: Client, flask_server: str) -> None:
    """A container names itself from the text no descendant line already prints."""
    await _open(client, flask_server, "/snapshot-names")

    lean = await _snapshot(client)
    assert lean.count("Panel body sentence") == 1
    assert lean.count("Panel action") == 1

    full = await _snapshot(client, interactive_only=False)
    for text in ("Panel heading", "Panel body sentence", "Panel action", "Alpha value"):
        assert full.count(text) == 1, f"{text} is printed twice:\n{full}"
