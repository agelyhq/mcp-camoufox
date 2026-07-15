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
