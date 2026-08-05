from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

SCROLL_Y_JS = "Math.round(window.scrollY)"


async def test_scroll_down(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/scroll", "profile": PROFILE})

    before = int(await evaluate(client, PROFILE, SCROLL_Y_JS))
    assert before == 0, "the page must start at the top for the delta to mean anything"

    result = tool_text(
        await client.call_tool("scroll", {"profile": PROFILE, "direction": "down", "amount": 600})
    )
    assert "scrolled" in result.lower()
    await asyncio.sleep(0.3)

    # The requested amount is the contract, not merely "some movement": a 1 px scroll
    # would satisfy "> 0" while leaving the model's mental model of the page wrong.
    js = await evaluate(client, PROFILE, SCROLL_Y_JS)
    assert int(js) == 600, f"asked to scroll 600px, landed at {js}"


async def test_scroll_element_into_view(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/scroll", "profile": PROFILE})

    before = int(await evaluate(client, PROFILE, SCROLL_Y_JS))

    await evaluate(
        client,
        PROFILE,
        "document.getElementById('section-10').scrollIntoView({behavior:'instant'})",
    )
    await asyncio.sleep(0.3)

    after = int(await evaluate(client, PROFILE, SCROLL_Y_JS))
    assert after > before


async def test_scroll_invalid_direction(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/scroll", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("scroll", {"profile": PROFILE, "direction": "sideways"})
    )
    assert "error" in result.lower()
