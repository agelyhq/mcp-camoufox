from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, goto_and_find, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_single_click(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Click me")

    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert "clicked" in result.lower()

    js = await text_content(client, PROFILE, "click-output")
    assert "single click detected" in js.lower()


async def test_double_click(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Double-click me")

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "uid": uid, "double_click": True})
    )
    assert "clicked" in result.lower()

    js = await text_content(client, PROFILE, "dblclick-output")
    assert "double click detected" in js.lower()


async def test_click_counter(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Count clicks")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})
    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    js = await text_content(client, PROFILE, "counter-output")
    assert "2" in js


async def test_click_invalid_uid(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": "e99999"}))
    assert "error" in result.lower()
    assert "stale uid" in result.lower()


async def test_click_bad_uid_format(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": "invalid"}))
    assert "error" in result.lower()
