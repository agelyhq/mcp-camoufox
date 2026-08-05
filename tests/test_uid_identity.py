"""A uid names an element, not a position, in exactly 1 tab and 1 document.

Under the previous scheme uids were assigned by walk order, so a re-render silently
renumbered them and ``e5`` in two captures could be two different elements. These
tests pin the new definition and the exact error strings that go with it.

The scope half matters as much as the identity half: while every tab and every
document numbered from ``e0``, a uid carried across either resolved to a valid but
different element and the action was reported as a success. So the tests below assert
both directions, that a uid survives everything inside its own document and that it
is refused everywhere else.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import (
    PROFILE,
    RENDERED_STALE_UID,
    evaluate,
    extract_uid,
    open_and_snapshot,
    snapshot_text,
    text_content,
    tool_text,
    uids,
)
from tests.waits import poll_tool_until

if TYPE_CHECKING:
    from fastmcp import Client


async def test_uid_survives_dom_mutation_around_it(client: Client, flask_server: str) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")

    await evaluate(
        client,
        PROFILE,
        "(() => { const rows = document.getElementById('rows'); "
        "for (let i = 0; i < 50; i++) { const b = document.createElement('button'); "
        "b.textContent = 'Filler ' + i; rows.insertBefore(b, rows.firstChild); } return 50; })()",
    )

    again = await snapshot_text(client)
    assert extract_uid(again, "Target row") == uid

    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert result.startswith("Clicked <button>")
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_recycled_uid_cannot_act_on_the_wrong_element(
    client: Client, flask_server: str
) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")

    await evaluate(
        client,
        PROFILE,
        "(() => { document.getElementById('target-btn').remove(); "
        "const rows = document.getElementById('rows'); "
        "for (let i = 0; i < 3; i++) { const b = document.createElement('button'); "
        "b.textContent = 'Replacement ' + i; rows.appendChild(b); } return 3; })()",
    )
    await snapshot_text(client)

    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert result == RENDERED_STALE_UID.format(uid=uid)
    assert "nothing clicked" in await text_content(client, PROFILE, "click-output")


async def test_new_element_gets_a_new_number(client: Client, flask_server: str) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    known = set(uids(snap))

    await evaluate(
        client,
        PROFILE,
        "(() => { const b = document.createElement('button'); b.id = 'fresh'; "
        "b.textContent = 'Fresh row'; document.getElementById('rows').appendChild(b); return 1; })()",
    )

    again = await snapshot_text(client)
    assert extract_uid(again, "Fresh row") not in known


async def test_navigation_starts_a_new_uid_range(client: Client, flask_server: str) -> None:
    """A new document numbers past every uid the previous one handed out.

    Restarting each document at ``e0`` is what let a held uid name a valid but
    different element after a navigation, so the ranges are asserted directly and not
    only through the wrong-element consequence below.
    """
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    before = set(uids(snap))

    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    fresh = set(uids(await snapshot_text(client)))

    assert before and fresh
    assert fresh.isdisjoint(before)
    beyond = f"e{max(int(uid[1:]) for uid in fresh) + 500}"
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": beyond}))
    assert result == RENDERED_STALE_UID.format(uid=beyond)


async def test_uid_from_the_previous_document_is_refused(client: Client, flask_server: str) -> None:
    """A uid belongs to 1 document: after a navigation it must go stale, not act.

    Measured before this was fixed: the uid of "Target row" clicked a button on the
    next page and the tool answered ``Clicked <button>``, a wrong element reported as
    a success.
    """
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")

    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    fresh = await snapshot_text(client)

    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert result == RENDERED_STALE_UID.format(uid=uid)
    assert "No click yet" in await text_content(client, PROFILE, "click-output")

    # The document is not broken, only that uid: its own uid for a button works.
    own = extract_uid(fresh, "Click me")
    assert tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": own})).startswith(
        "Clicked <button>"
    )


async def test_uid_from_another_tab_is_refused(client: Client, flask_server: str) -> None:
    """A uid belongs to 1 tab, even when the other tab shows the same document.

    Both tabs load ``/identity``, so tab B holds an element at exactly the position
    tab A numbered. With every tab numbering from ``e0`` that made tab A's uid resolve
    on tab B and click it, which is the silent wrong-element failure this scheme
    exists to close.
    """
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")

    await client.call_tool("new_page", {"profile": PROFILE, "url": f"{flask_server}/identity"})
    other = await snapshot_text(client)

    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert result == RENDERED_STALE_UID.format(uid=uid)
    assert "nothing clicked" in await text_content(client, PROFILE, "click-output")

    # The tab is not broken, only that uid: its own uid for the same element works.
    own = extract_uid(other, "Target row")
    assert tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": own})).startswith(
        "Clicked <button>"
    )
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_same_document_navigation_preserves_uids(client: Client, flask_server: str) -> None:
    """A pushState keeps the execution context alive, so it must keep the uids too."""
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")

    await evaluate(client, PROFILE, "history.pushState({}, '', '/identity?step=2')")

    again = await snapshot_text(client)
    assert extract_uid(again, "Target row") == uid
    assert tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid})).startswith(
        "Clicked <button>"
    )


async def test_stale_uid_message_is_exact(client: Client, flask_server: str) -> None:
    """Every uid consumer renders the mandated string byte for byte."""
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")
    await evaluate(client, PROFILE, "document.getElementById('target-btn').remove()")

    expected = RENDERED_STALE_UID.format(uid=uid)
    calls = [
        ("click", {"profile": PROFILE, "uid": uid}),
        ("fill", {"profile": PROFILE, "uid": uid, "value": "x"}),
        ("scroll", {"profile": PROFILE, "uid": uid}),
        ("screenshot", {"profile": PROFILE, "uid": uid}),
        ("upload_file", {"profile": PROFILE, "uid": uid, "file_path": __file__}),
        ("get_element", {"profile": PROFILE, "uid": uid}),
        ("evaluate", {"profile": PROFILE, "script": "(el) => el.tagName", "uids": [uid]}),
    ]
    for name, args in calls:
        result = await client.call_tool(name, args)
        # screenshot declares an image return, so an error string lands in the
        # content block rather than in .data.
        rendered = tool_text(result) if name != "screenshot" else result.content[0].text
        assert rendered == expected, name


async def test_navigation_midflight_yields_the_mandated_string(
    client: Client, flask_server: str
) -> None:
    """A fill racing a navigation must never surface a raw context-destroyed message."""
    snap = await open_and_snapshot(client, f"{flask_server}/identity")
    uid = extract_uid(snap, "Target row")

    fill, _ = await asyncio.gather(
        client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "x"}),
        client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE}),
    )
    result = tool_text(fill)
    assert "Execution context was destroyed" not in result
    assert result.startswith(("Filled <", "Error: ValueError:"))


async def test_closed_page_is_not_reported_as_stale(client: Client, flask_server: str) -> None:
    """A dead tab is a TargetClosedError, never "take a new snapshot".

    Mapping a browser that is gone to a re-snapshot instruction sends an agent into
    an unbounded retry loop, so the type is re-raised before any uid reasoning runs.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/identity", "profile": PROFILE})
    await client.call_tool("new_page", {"profile": PROFILE, "url": f"{flask_server}/identity"})
    snap = await snapshot_text(client)
    uid = extract_uid(snap, "Target row")

    await evaluate(client, PROFILE, "window.close()")
    # The close crosses the protocol asynchronously. Clicking while the tab is still
    # alive is an ordinary successful click, so the mapping under test would never be
    # exercised and the test would pass having proved nothing. Probe the tab until it
    # stops answering: that is the precondition, and the click below is the assertion.
    await poll_tool_until(
        client,
        "evaluate",
        {"profile": PROFILE, "script": "1"},
        lambda text: "TargetClosedError" in text,
        describe="the closed tab never stopped answering evaluate",
    )

    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))

    assert result.startswith("Error: TargetClosedError:")
    assert "take a new snapshot" not in result
