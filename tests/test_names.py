"""The accessible name a snapshot line carries, on the markup ordinary pages use.

A name that folds in the page's own data is worse than no name, and a control with no
name at all is unreachable: under the interactive-only default nothing else prints the
text that would have identified it. Both failures are cheap to reintroduce, so every
shape below is a real page rendered by a real browser.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, line_with, open_page, snapshot_text, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_wrapping_label_leaves_the_control_data_out(
    client: Client, flask_server: str
) -> None:
    """A <label> around a control names it, without folding in what the control holds."""
    await open_page(client, f"{flask_server}/names-labels")

    snap = await snapshot_text(client)

    # The option list and the field contents are data; neither is anyone's name.
    assert "Apple Berry" not in snap and "AppleBerry" not in snap, snap
    assert "SECRETDATA" not in snap, snap
    fruit = line_with(snap, "name=fruit")
    assert re.fullmatch(r"\s*\[select e\d+\] Pick fruit \(name=fruit, value=a, Apple\)", fruit), (
        fruit
    )
    notes = line_with(snap, "name=notes")
    assert re.fullmatch(r"\s*\[textarea e\d+\] Notes \(name=notes\)", notes), notes


async def test_labelledby_target_leaves_its_data_out(client: Client, flask_server: str) -> None:
    """The same rule through aria-labelledby: a referenced block can hold data too."""
    await open_page(client, f"{flask_server}/names-labels")

    snap = await snapshot_text(client)

    assert "Region East" not in snap and "EastWest" not in snap, snap
    assert "CellOneCellTwo" not in snap and "CellOne CellTwo" not in snap, snap
    region = line_with(snap, "name=region_code")
    assert re.fullmatch(r"\s*\[input:text e\d+\] Region \(name=region_code\)", region), region
    summary = line_with(snap, "name=summary_code")
    assert re.fullmatch(r"\s*\[input:text e\d+\] Summary \(name=summary_code\)", summary), summary


async def test_icon_control_is_named_by_its_image(client: Client, flask_server: str) -> None:
    """An icon link and an icon button own no text: the image alt is their only name."""
    await open_page(client, f"{flask_server}/names-labels")

    snap = await snapshot_text(client)

    link = line_with(snap, "Home page")
    assert re.fullmatch(r"\s*\[a e\d+\] Home page \(href=/home\)", link), link
    button = line_with(snap, "Delete row")
    assert re.fullmatch(r"\s*\[button e\d+\] Delete row", button), button


async def test_icon_control_is_reachable_by_name(client: Client, flask_server: str) -> None:
    """What the name is for: `find` reaches a control that carries no text of its own."""
    await open_page(client, f"{flask_server}/names-labels")

    found = tool_text(
        await client.call_tool("find", {"profile": PROFILE, "role": "button", "name": "Delete row"})
    )

    assert found.startswith("[found 1/1]"), found
    assert "Delete row" in found


async def test_repeated_blocks_are_told_apart(client: Client, flask_server: str) -> None:
    """3 equivalent container shapes, 3 identical buttons: each block must name itself."""
    await open_page(client, f"{flask_server}/names-containers")

    lines = (await snapshot_text(client)).splitlines()

    edits = [i for i, line in enumerate(lines) if re.fullmatch(r"\s*\[button e\d+\] Edit", line)]
    named = [i for i, line in enumerate(lines) if "address" in line]
    assert len(edits) == 3, lines
    # Every button is preceded by the block it belongs to, so no 2 of them read alike.
    assert [i + 1 for i in named] == edits, lines
    assert re.fullmatch(r"\s*\[section\] Home address", lines[named[0]]), lines[named[0]]
    assert re.fullmatch(r"\s*\[article\] Work address", lines[named[1]]), lines[named[1]]
    assert lines[named[2]].strip().startswith("[div] Billing address"), lines[named[2]]


async def test_hoisted_name_is_not_printed_twice(client: Client, flask_server: str) -> None:
    """Hoisting borrows only text no other line prints, so the full tree says it once."""
    await open_page(client, f"{flask_server}/names-containers")

    full = await snapshot_text(client, interactive_only=False)

    # The heading-owning <div> is a block like the other 2 and gets a line of its own,
    # so all 3 shapes nest their button the same way.
    assert len([line for line in full.splitlines() if line.strip() == "[div]"]) == 1, full
    for text in ("Home address", "Work address", "Billing address"):
        assert full.count(text) == 1, f"{text} is printed twice:\n{full}"
