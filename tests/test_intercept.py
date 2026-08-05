"""A covered click fails and names what covered it, instead of reporting success.

Before this change a click on an element under a full-page interstitial reported
``Clicked <button> at (x, y)`` while every event went to the banner. The hit test
also has to stay quiet on the cases that only look like interception: a child span
inside its own button, and a label sitting over the control it activates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import (
    PROFILE,
    evaluate,
    extract_uid,
    open_and_snapshot,
    open_page,
    snapshot_text,
    text_content,
    tool_text,
)

if TYPE_CHECKING:
    from fastmcp import Client

SHOW_BANNER_JS = "document.getElementById('veil').style.display = 'block'"
# The veil comes down on the click's OWN first hit test, instead of on a timer racing
# it. 00_boot.js captures `Document.prototype.elementsFromPoint` when the store first
# runs, and 50_geometry.js `hitTest` is the only caller, so a wrapper installed before
# the first snapshot counts exactly the probes and can hide the veil between two of
# them. A timer here decided the outcome by machine speed: fire before the click
# starts probing and the retry path is never exercised, while the test still passes.
HIDE_ON_FIRST_HIT_TEST_JS = """
(() => {
  window.__blockedProbes = 0;
  const veil = document.getElementById('veil');
  const original = Document.prototype.elementsFromPoint;
  Document.prototype.elementsFromPoint = function (x, y) {
    const stack = original.call(this, x, y);
    if (veil.style.display === 'block') {
      window.__blockedProbes++;
      veil.style.display = 'none';
    }
    return stack;
  };
  return 1;
})()
"""
GHOST_BANNER_JS = (
    "(() => { const b = document.getElementById('veil'); "
    "b.style.display = 'block'; b.style.pointerEvents = 'none'; return 1; })()"
)


async def _click(client: Client, uid: str) -> str:
    return tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))


async def test_click_under_fixed_overlay_reports_the_interceptor(
    client: Client, flask_server: str
) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
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
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
    uid = extract_uid(snap, "Target")
    await evaluate(client, PROFILE, SHOW_BANNER_JS)

    dismissed = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#dismiss"})
    )
    assert dismissed.startswith("Clicked <button>")

    assert (await _click(client, uid)).startswith("Clicked <button>")
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_click_waits_out_a_disappearing_overlay(client: Client, flask_server: str) -> None:
    """The poll retries interception; failing on the first probe would be wrong.

    The overlay is taken down by the click's own first hit test, so the click is
    guaranteed to meet it once and can only succeed on a later probe. One probe
    taken while the veil was up is the proof the retry ran, which the removed
    800 ms timer hoped for rather than established.
    """
    await open_page(client, f"{flask_server}/overlay")
    assert await evaluate(client, PROFILE, HIDE_ON_FIRST_HIT_TEST_JS) == "1"
    snap = await snapshot_text(client)
    uid = extract_uid(snap, "Target")
    assert await evaluate(client, PROFILE, "window.__blockedProbes") == "0", "the walk hit tests"
    await evaluate(client, PROFILE, SHOW_BANNER_JS)

    result = await _click(client, uid)

    assert result.startswith("Clicked <button>"), result
    assert "target clicked" in await text_content(client, PROFILE, "click-output")
    blocked = int(await evaluate(client, PROFILE, "window.__blockedProbes"))
    assert blocked == 1, (
        f"{blocked} hit test(s) met the overlay, so the click never had to wait it out: "
        "either the retry is gone, or the hit test no longer goes through "
        "elementsFromPoint and this test has to be re-anchored on whatever it probes now"
    )


async def test_pointer_events_none_overlay_does_not_intercept(
    client: Client, flask_server: str
) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
    uid = extract_uid(snap, "Target")
    await evaluate(client, PROFILE, GHOST_BANNER_JS)

    assert (await _click(client, uid)).startswith("Clicked <button>")
    assert "target clicked" in await text_content(client, PROFILE, "click-output")


async def test_span_inside_button_is_not_an_interception(client: Client, flask_server: str) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
    uid = extract_uid(snap, "Send")

    assert (await _click(client, uid)).startswith("Clicked <button>")
    assert "span button clicked" in await text_content(client, PROFILE, "span-output")


async def test_label_over_input_is_not_an_interception(client: Client, flask_server: str) -> None:
    """The label covers its own checkbox, and clicking it is what activates it."""
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
    uid = extract_uid(snap, "Accept terms")

    assert (await _click(client, uid)).startswith("Clicked <input>")
    assert "checkbox on" in await text_content(client, PROFILE, "skin-output")


async def test_zero_size_is_not_reported_as_stale(client: Client, flask_server: str) -> None:
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
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
    snap = await open_and_snapshot(client, f"{flask_server}/overlay")
    uid = extract_uid(snap, "Clipped away")

    result = await _click(client, uid)

    assert "cannot be scrolled into the viewport" in result
    assert "take a new snapshot" not in result
