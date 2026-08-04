from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, goto_and_find, text_content, tool_text

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


async def test_fill_select_by_value(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Choose option")

    result = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "banana"})
    )
    assert "selected" in result.lower()

    js = await text_content(client, PROFILE, "select-output")
    assert "banana" in js


async def test_fill_select_by_label(client: Client, flask_server: str) -> None:
    """The visible label works too, which is what an agent reads off a snapshot."""
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Choose option")

    await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "Cherry"})

    js = await text_content(client, PROFILE, "select-output")
    assert "cherry" in js


async def test_fill_select_unknown_option_lists_choices(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Choose option")

    result = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "durian"})
    )
    assert "error" in result.lower()
    assert "Apple" in result and "Banana" in result


async def test_fill_non_editable(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Index")

    result = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "text"})
    )
    assert "error" in result.lower()


async def test_fill_plain_uid_output_unchanged(client: Client, flask_server: str) -> None:
    """Regression: default observe='none' appends nothing and keeps the uid format."""
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Name")

    result = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "Hello MCP"})
    )
    assert result.startswith("Filled <")
    assert result.endswith("with 9 chars")
    assert "observation" not in result


async def test_fill_by_selector(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "fill", {"profile": PROFILE, "selector": "#text-input", "value": "Hello selector"}
        )
    )
    assert "filled" in result.lower()
    assert "#text-input" in result

    js = await text_content(client, PROFILE, "text-output")
    assert "Hello selector" in js


async def test_fill_selector_both_errors(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill", "profile": PROFILE})
    result = tool_text(
        await client.call_tool(
            "fill",
            {"profile": PROFILE, "uid": "e0", "selector": "#text-input", "value": "x"},
        )
    )
    assert "error" in result.lower()
    assert "exactly one of uid or selector" in result.lower()


async def test_fill_selector_neither_errors(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill", "profile": PROFILE})
    result = tool_text(await client.call_tool("fill", {"profile": PROFILE, "value": "x"}))
    assert "error" in result.lower()
    assert "exactly one of uid or selector" in result.lower()


async def test_fill_observe_snapshot_yields_usable_uids(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Name")

    result = tool_text(
        await client.call_tool(
            "fill", {"profile": PROFILE, "uid": uid, "value": "hi", "observe": "snapshot"}
        )
    )
    assert "filled" in result.lower()
    assert "--- observation (snapshot) ---" in result

    # The fresh observation exposes usable uids for the rest of the form.
    email_uid = extract_uid(result, "email")
    assert email_uid.startswith("e")


async def test_fill_invalid_observe_rejected(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/fill", PROFILE, "Name")
    result = tool_text(
        await client.call_tool(
            "fill", {"profile": PROFILE, "uid": uid, "value": "x", "observe": "bogus"}
        )
    )
    assert "error" in result.lower()
    assert "invalid observe" in result.lower()
