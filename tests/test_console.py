from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, extract_uid, goto_and_find, tool_text
from tests.waits import poll_tool_or_last, poll_tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# A console message is delivered to the Python-side monitor by an asynchronous protocol
# event, so no page-side wait can prove it arrived: the listing is the only observable.


async def test_list_console_messages_log(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/console", PROFILE, "Log message")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    result = await poll_tool_text(
        client, "list_console_messages", {"profile": PROFILE}, "hello from log"
    )
    assert "hello from log" in result


async def test_list_console_messages_error(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/console", PROFILE, "Error message")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    # Polled through the filtered call, so the condition waited on is the condition
    # asserted.
    result = await poll_tool_text(
        client,
        "list_console_messages",
        {"profile": PROFILE, "levels": ["error"]},
        "something went wrong",
    )
    assert "something went wrong" in result


async def test_list_console_messages_filter_excludes(client: Client, flask_server: str) -> None:
    """The level filter drops the log message once both messages have been captured.

    The assertion at the end is an absence, which passes for free if the log message has
    simply not arrived yet: the filter would never be exercised. So the precondition
    (both messages captured) is polled on the UNFILTERED listing first.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/console", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    log_uid = extract_uid(snap, "Log message")
    err_uid = extract_uid(snap, "Error message")

    await client.call_tool("click", {"profile": PROFILE, "uid": log_uid})
    await client.call_tool("click", {"profile": PROFILE, "uid": err_uid})

    captured = await poll_tool_or_last(
        client,
        "list_console_messages",
        {"profile": PROFILE},
        lambda text: "something went wrong" in text and "hello from log" in text,
    )
    assert "hello from log" in captured, captured
    assert "something went wrong" in captured, captured

    result = tool_text(
        await client.call_tool("list_console_messages", {"profile": PROFILE, "levels": ["error"]})
    )
    assert "something went wrong" in result
    assert "hello from log" not in result


async def test_list_console_messages_limit(client: Client, flask_server: str) -> None:
    """``limit`` returns the newest messages only.

    The burst's LAST message arriving is the precondition: with only three captured, the
    window would read multi-1/multi-2 and the exact assertions below would fail.
    """
    uid = await goto_and_find(client, f"{flask_server}/console", PROFILE, "Log multiple")

    await client.call_tool("click", {"profile": PROFILE, "uid": uid})

    await poll_tool_text(client, "list_console_messages", {"profile": PROFILE}, "multi-4")

    result = tool_text(
        await client.call_tool("list_console_messages", {"profile": PROFILE, "limit": 2})
    )
    assert "multi-3" in result
    assert "multi-4" in result
    assert "multi-0" not in result


async def test_list_console_messages_empty(client: Client, flask_server: str) -> None:
    """A freshly navigated page renders the empty state.

    What this pins is the empty-state rendering and the fact that a navigation leaves the
    default (non-preserved) listing empty. It is not proof that no message can ever
    arrive: run right after ``navigate``, it would also pass on a merely late message.
    The page emits no console output by construction, and the per-test session
    (tests/conftest.py) guarantees nothing leaks in from another test.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/console", "profile": PROFILE})

    result = tool_text(await client.call_tool("list_console_messages", {"profile": PROFILE}))
    assert "No console messages" in result
