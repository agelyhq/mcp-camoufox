from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import (
    OBSERVATION_SNAPSHOT_MARK,
    PROFILE,
    evaluate,
    open_page,
    text_content,
    tool_text,
)
from tests.waits import wait_predicate

if TYPE_CHECKING:
    from fastmcp import Client

CENTER_JS = """
(() => {
  const r = document.getElementById('click-area').getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
})()
"""

# Counts what the box actually received (single clicks and double clicks) and returns
# the box centre, so a test can assert on the page rather than on the tool's own echo.
CENTER_AND_COUNTERS_JS = """
(() => {
  window.__clicks = 0;
  window.__dblclicks = 0;
  const box = document.getElementById('click-area');
  box.addEventListener('click', () => { window.__clicks += 1; });
  box.addEventListener('dblclick', () => { window.__dblclicks += 1; });
  const r = box.getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
})()
"""

# Installs a click counter on the box and returns its bounding rect so tests can
# aim several in-bounds points.
RECT_AND_COUNTER_JS = """
(() => {
  window.__clicks = 0;
  const box = document.getElementById('click-area');
  box.addEventListener('click', () => { window.__clicks += 1; });
  const r = box.getBoundingClientRect();
  return {x: r.x, y: r.y, w: r.width, h: r.height};
})()
"""


async def test_click_at_coordinates(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click-at")

    center = json.loads(await evaluate(client, PROFILE, CENTER_JS))

    result = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": center["x"], "y": center["y"]})
    )
    assert "clicked at" in result.lower()
    await wait_predicate(
        client,
        PROFILE,
        "document.getElementById('coord-output').textContent !== 'no click'",
        timeout_ms=5000,
    )

    js = await text_content(client, PROFILE, "coord-output")
    assert "clicked at" in js.lower()


async def test_click_at_double(client: Client, flask_server: str) -> None:
    """A double click is asserted on the page, not on the tool's echo of its argument.

    ``"double-clicked at" in result`` is rendered from the ``double_click=True`` the
    caller passed in, so it cannot tell ``click_count=2`` from ``click_count=1``: only a
    crash failed it. The box's own ``dblclick`` listener can.
    """
    await open_page(client, f"{flask_server}/click-at")

    center = json.loads(await evaluate(client, PROFILE, CENTER_AND_COUNTERS_JS))

    result = tool_text(
        await client.call_tool(
            "click_at",
            {"profile": PROFILE, "x": center["x"], "y": center["y"], "double_click": True},
        )
    )
    assert "double-clicked at" in result.lower()

    await wait_predicate(client, PROFILE, "window.__dblclicks === 1", timeout_ms=5000)
    assert (await evaluate(client, PROFILE, "window.__clicks")).strip() == "2"


async def test_click_at_single_output_unchanged(client: Client, flask_server: str) -> None:
    """Regression: single-point output and no observation block by default."""
    await open_page(client, f"{flask_server}/click-at")
    center = json.loads(await evaluate(client, PROFILE, CENTER_JS))

    result = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": center["x"], "y": center["y"]})
    )
    assert result.startswith("Clicked at (")
    assert "observation" not in result
    assert "points" not in result


async def test_click_at_points_batch(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click-at")
    rect = json.loads(await evaluate(client, PROFILE, RECT_AND_COUNTER_JS))
    points = [
        [rect["x"] + 40, rect["y"] + 40],
        [rect["x"] + 90, rect["y"] + 90],
        [rect["x"] + 140, rect["y"] + 140],
    ]

    result = tool_text(await client.call_tool("click_at", {"profile": PROFILE, "points": points}))
    assert "clicked 3 points at" in result.lower()
    await wait_predicate(client, PROFILE, "window.__clicks === 3", timeout_ms=5000)

    # Exact, so a fourth click would fail here instead of hiding inside a nap.
    clicks = await evaluate(client, PROFILE, "window.__clicks")
    assert clicks.strip() == "3"


async def test_click_at_points_observe_applied_once(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click-at")
    rect = json.loads(await evaluate(client, PROFILE, RECT_AND_COUNTER_JS))
    points = [
        [rect["x"] + 30, rect["y"] + 30],
        [rect["x"] + 80, rect["y"] + 80],
    ]

    result = tool_text(
        await client.call_tool(
            "click_at", {"profile": PROFILE, "points": points, "observe": "snapshot"}
        )
    )
    assert "clicked 2 points at" in result.lower()
    # The observation is appended exactly once, after the last click — not per point.
    assert result.count(OBSERVATION_SNAPSHOT_MARK) == 1


async def test_click_at_both_single_and_points_errors(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click-at")
    result = tool_text(
        await client.call_tool(
            "click_at", {"profile": PROFILE, "x": 10, "y": 10, "points": [[20, 20]]}
        )
    )
    assert "error" in result.lower()
    assert "provide exactly one" in result.lower()


async def test_click_at_neither_single_nor_points_errors(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click-at")
    result = tool_text(await client.call_tool("click_at", {"profile": PROFILE}))
    assert "error" in result.lower()
    assert "provide exactly one" in result.lower()
