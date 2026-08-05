"""A covered click fails and names what covered it, instead of reporting success.

Before this change a click on an element under a full-page interstitial reported
``Clicked <button> at (x, y)`` while every event went to the banner. The hit test
also has to stay quiet on the cases that only look like interception: a child span
inside its own button, and a label sitting over the control it activates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

SHOW_BANNER_JS = "document.getElementById('veil').style.display = 'block'"
HIDE_LATER_JS = (
    "(() => { const b = document.getElementById('veil'); "
    "b.style.display = 'block'; "
    "setTimeout(() => { b.style.display = 'none'; }, 800); return 1; })()"
)
GHOST_BANNER_JS = (
    "(() => { const b = document.getElementById('veil'); "
    "b.style.display = 'block'; b.style.pointerEvents = 'none'; return 1; })()"
)


async def _open(client: Client, flask_server: str) -> str:
    await client.call_tool("navigate", {"url": f"{flask_server}/overlay", "profile": PROFILE})
    return tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))


async def _click(client: Client, uid: str) -> str:
    return tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))


async def test_click_under_fixed_overlay_reports_the_interceptor(
    client: Client, flask_server: str
) -> None:
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Target")
    await evaluate(client, PROFILE, SHOW_BANNER_JS)

    result = await _click(client, uid)

    assert result.startswith("Error: ElementInterceptedError:")
    assert "veil" in result
    assert f"uid '{uid}'" in result
    assert "(<button>)" in result
    assert "nothing clicked" in await text_content(client, PROFILE, "click-output")


async def test_click_succeeds_once_the_overlay_is_dismissed(
    client: Client, flask_server: str
) -> None:
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Target")
    await evaluate(client, PROFILE, SHOW_BANNER_JS)

    dismissed = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#dismiss"})
    )
    assert dismissed.startswith("Clicked <button>")

    assert (await _click(client, uid)).startswith("Clicked <button>")
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_click_waits_out_a_disappearing_overlay(client: Client, flask_server: str) -> None:
    """The poll retries interception; failing on the first probe would be wrong."""
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Target")
    await evaluate(client, PROFILE, HIDE_LATER_JS)

    result = await _click(client, uid)

    assert result.startswith("Clicked <button>"), result
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_pointer_events_none_overlay_does_not_intercept(
    client: Client, flask_server: str
) -> None:
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Target")
    await evaluate(client, PROFILE, GHOST_BANNER_JS)

    assert (await _click(client, uid)).startswith("Clicked <button>")
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_span_inside_button_is_not_an_interception(client: Client, flask_server: str) -> None:
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Send")

    assert (await _click(client, uid)).startswith("Clicked <button>")
    assert "span button clicked" in await text_content(client, PROFILE, "span-output")


async def test_label_over_input_is_not_an_interception(client: Client, flask_server: str) -> None:
    """The label covers its own checkbox, and clicking it is what activates it."""
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Accept terms")

    assert (await _click(client, uid)).startswith("Clicked <input>")
    assert "checkbox on" in await text_content(client, PROFILE, "skin-output")


async def test_zero_size_is_not_reported_as_stale(client: Client, flask_server: str) -> None:
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Shrink me")
    await evaluate(
        client,
        PROFILE,
        "(() => { const b = document.getElementById('shrinker'); "
        "b.textContent = ''; b.style.display = 'inline'; b.style.padding = '0'; "
        "b.style.border = 'none'; return 1; })()",
    )

    result = await _click(client, uid)

    assert "zero size; it is present but not rendered" in result
    assert "take a new snapshot" not in result


async def test_offscreen_element_reports_its_own_error(client: Client, flask_server: str) -> None:
    snap = await _open(client, flask_server)
    uid = extract_uid(snap, "Clipped away")

    result = await _click(client, uid)

    assert "cannot be scrolled into the viewport" in result
    assert "take a new snapshot" not in result
