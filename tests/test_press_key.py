from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_press_arrow_key(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowRight"})
    )
    assert "pressed" in result.lower()

    js = await text_content(client, PROFILE, "key-display")
    assert json.loads(js) == "ArrowRight", js


async def test_press_key_moves_marker(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowDown"})
    await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowDown"})

    # The marker starts at (140, 90) and each ArrowDown moves it 10px, so two presses
    # land it at exactly (140, 110): "110" in the blob would also match "1101" or an
    # unrelated x coordinate.
    js = await text_content(client, PROFILE, "position-output")
    assert json.loads(js) == "Position: (140, 110)", js


async def test_press_key_combo(client: Client, flask_server: str) -> None:
    """A modifier combo delivers both halves.

    `"Shift" in js` also passed for a bare Shift keypress, i.e. for a combo whose
    non-modifier half was silently dropped. The page renders the full combo, so
    assert the whole of it.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    await client.call_tool("press_key", {"profile": PROFILE, "key": "Shift+A"})

    js = await text_content(client, PROFILE, "key-display")
    assert json.loads(js) == "Shift+A", js
