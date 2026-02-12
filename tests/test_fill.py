from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import extract_uid, tool_text


async def test_fill_text_input(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "text")

    result = tool_text(await client.call_tool("fill", {"uid": uid, "value": "Hello MCP"}))
    assert "filled" in result.lower()

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('text-output').textContent"},
        )
    )
    assert "Hello MCP" in js


async def test_fill_email(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "email")

    await client.call_tool("fill", {"uid": uid, "value": "test@example.com"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {
                "script": "({v: document.getElementById('email-output').textContent, "
                "valid: document.getElementById('email-validity').textContent})"
            },
        )
    )
    assert "test@example.com" in js
    assert "true" in js.lower()


async def test_fill_textarea(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "textarea")

    await client.call_tool("fill", {"uid": uid, "value": "Multi-line text"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('textarea-output').textContent"},
        )
    )
    assert "Multi-line text" in js


async def test_fill_contenteditable(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Edit this")

    await client.call_tool("fill", {"uid": uid, "value": "Edited content"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('editable-output').textContent"},
        )
    )
    assert "Edited content" in js


async def test_fill_select(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "[select")

    await client.call_tool("fill", {"uid": uid, "value": "Cherry"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "document.getElementById('select-output').textContent"},
        )
    )
    assert "cherry" in js.lower()


async def test_fill_non_editable(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill"})
    snap = tool_text(await client.call_tool("take_snapshot", {}))
    uid = extract_uid(snap, "Index")

    result = tool_text(await client.call_tool("fill", {"uid": uid, "value": "text"}))
    assert "error" in result.lower()
