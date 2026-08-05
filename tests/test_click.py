from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, goto_and_find, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# Grows the page body innerText past the 4000-char observe=text cap.
_BIG_TEXT_JS = (
    "document.body.insertAdjacentHTML('beforeend', '<p>' + 'x'.repeat(5000) + '</p>'); 'ok'"
)


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

    # Exactly two, not "a 2 appears somewhere": a substring check also accepts 12 or 20.
    js = await text_content(client, PROFILE, "counter-output")
    assert json.loads(js) == "Clicked 2 time(s)", js


async def test_click_invalid_uid(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": "e99999"}))
    assert "error" in result.lower()
    assert "stale uid" in result.lower()


async def test_click_bad_uid_format(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": "invalid"}))
    assert "error" in result.lower()


async def test_click_plain_uid_output_unchanged(client: Client, flask_server: str) -> None:
    """Regression: default observe='none' appends nothing and keeps the uid format."""
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Click me")
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert result.startswith("Clicked <")
    assert " at (" in result
    assert "observation" not in result


async def test_click_by_selector(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#btn-single"})
    )
    assert "clicked" in result.lower()
    assert "#btn-single" in result

    js = await text_content(client, PROFILE, "click-output")
    assert "single click detected" in js.lower()


async def test_click_selector_both_errors(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    result = tool_text(
        await client.call_tool(
            "click", {"profile": PROFILE, "uid": "e0", "selector": "#btn-single"}
        )
    )
    assert "error" in result.lower()
    assert "exactly one of uid or selector" in result.lower()


async def test_click_selector_neither_errors(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    result = tool_text(await client.call_tool("click", {"profile": PROFILE}))
    assert "error" in result.lower()
    assert "exactly one of uid or selector" in result.lower()


async def test_click_observe_snapshot_yields_usable_uids(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Click me")

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "uid": uid, "observe": "snapshot"})
    )
    assert "clicked" in result.lower()
    assert "--- observation (snapshot) ---" in result

    # A uid taken from the fresh observation must drive a follow-up click.
    counter_uid = extract_uid(result, "Count clicks")
    follow = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": counter_uid}))
    assert "clicked" in follow.lower()

    js = await text_content(client, PROFILE, "counter-output")
    assert json.loads(js) == "Clicked 1 time(s)", js


async def test_click_observe_text_truncates(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Click me")
    await evaluate(client, PROFILE, _BIG_TEXT_JS)

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "uid": uid, "observe": "text"})
    )
    assert "clicked" in result.lower()
    assert "--- observation (text) ---" in result
    assert "[truncated" in result
    # 5000 'x' were injected; the 4000-char cap keeps a long-but-partial run, so
    # a big contiguous block survives while the full 5000 never does.
    assert "x" * 2000 in result
    assert "x" * 5000 not in result


async def test_click_invalid_observe_rejected(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/click", PROFILE, "Click me")
    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "uid": uid, "observe": "screenshot"})
    )
    assert "error" in result.lower()
    assert "invalid observe" in result.lower()
