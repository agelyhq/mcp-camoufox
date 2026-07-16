from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

CENTER_JS = """
(() => {
  const r = document.getElementById('click-area').getBoundingClientRect();
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
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})

    center = json.loads(await evaluate(client, PROFILE, CENTER_JS))

    result = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": center["x"], "y": center["y"]})
    )
    assert "clicked at" in result.lower()
    await asyncio.sleep(0.2)

    js = await text_content(client, PROFILE, "coord-output")
    assert "clicked at" in js.lower()


async def test_click_at_double(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})

    center = json.loads(await evaluate(client, PROFILE, CENTER_JS))

    result = tool_text(
        await client.call_tool(
            "click_at",
            {"profile": PROFILE, "x": center["x"], "y": center["y"], "double_click": True},
        )
    )
    assert "double-clicked at" in result.lower()


async def test_click_at_single_output_unchanged(client: Client, flask_server: str) -> None:
    """Regression: single-point output and no observation block by default."""
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})
    center = json.loads(await evaluate(client, PROFILE, CENTER_JS))

    result = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": center["x"], "y": center["y"]})
    )
    assert result.startswith("Clicked at (")
    assert "observation" not in result
    assert "points" not in result


async def test_click_at_points_batch(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})
    rect = json.loads(await evaluate(client, PROFILE, RECT_AND_COUNTER_JS))
    points = [
        [rect["x"] + 40, rect["y"] + 40],
        [rect["x"] + 90, rect["y"] + 90],
        [rect["x"] + 140, rect["y"] + 140],
    ]

    result = tool_text(await client.call_tool("click_at", {"profile": PROFILE, "points": points}))
    assert "clicked 3 points at" in result.lower()
    await asyncio.sleep(0.2)

    clicks = await evaluate(client, PROFILE, "window.__clicks")
    assert clicks.strip() == "3"


async def test_click_at_points_observe_applied_once(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})
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
    assert result.count("--- observation (snapshot) ---") == 1


async def test_click_at_both_single_and_points_errors(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})
    result = tool_text(
        await client.call_tool(
            "click_at", {"profile": PROFILE, "x": 10, "y": 10, "points": [[20, 20]]}
        )
    )
    assert "error" in result.lower()
    assert "provide exactly one" in result.lower()


async def test_click_at_neither_single_nor_points_errors(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click-at", "profile": PROFILE})
    result = tool_text(await client.call_tool("click_at", {"profile": PROFILE}))
    assert "error" in result.lower()
    assert "provide exactly one" in result.lower()
