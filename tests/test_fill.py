from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, goto_and_find, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_fill_text_input(client: Client, flask_server: str) -> None:
    # "Name" is the accessible label of the intended text input; the old "text"
    # label also matched "textarea"/"text-output".
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Name")

    result = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "Hello MCP"})
    )
    assert "filled" in result.lower()

    js = await text_content(client, PROFILE, "text-output")
    assert "Hello MCP" in js


async def test_fill_email(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "email")

    await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "test@example.com"})

    js = await evaluate(
        client,
        PROFILE,
        "({v: document.getElementById('email-output').textContent, "
        "valid: document.getElementById('email-validity').textContent})",
    )
    assert "test@example.com" in js
    assert "true" in js.lower()


async def test_fill_textarea(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "textarea")

    await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "Multi-line text"})

    js = await text_content(client, PROFILE, "textarea-output")
    assert "Multi-line text" in js


async def test_fill_contenteditable(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Edit this")

    await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "Edited content"})

    js = await text_content(client, PROFILE, "editable-output")
    assert "Edited content" in js


async def test_fill_non_editable(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Index")

    result = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "text"})
    )
    assert "error" in result.lower()
