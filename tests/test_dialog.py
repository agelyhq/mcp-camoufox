from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, open_page, tool_text
from tests.waits import poll_tool_or_last

if TYPE_CHECKING:
    from fastmcp import Client

NO_PENDING = "Error: NoPendingDialogError: No dialog is pending"

# A dialog arrives on the browser's own schedule, so the poll is short-intervalled;
# the deadline only bounds one that never arrives.
_POLL_INTERVAL_S = 0.05


async def _answer_dialog(client: Client, action: str, *, prompt_text: str | None = None) -> str:
    """Answer the pending dialog, retrying until one is pending; return the answer.

    A modal blocks the page, so ``evaluate`` and ``wait_for`` would hang: there is no
    page-side observable at all here, and the tool itself is the only one. Answering
    when nothing is pending consumes nothing, so the retry is safe, and the first
    non-error answer IS the assertion, which is why expiry hands back the last output
    instead of raising on it.
    """
    args: dict[str, object] = {"profile": PROFILE, "action": action}
    if prompt_text is not None:
        args["prompt_text"] = prompt_text
    return await poll_tool_or_last(
        client, "handle_dialog", args, lambda text: text != NO_PENDING, interval=_POLL_INTERVAL_S
    )


async def test_handle_alert(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/dialog")

    await evaluate(client, PROFILE, "setTimeout(() => alert('Test alert'), 0)")

    result = await _answer_dialog(client, "accept")
    assert result == "Dialog accepted", result
    # The dialog is consumed, not just reported: a second call finds nothing pending.
    # `"accept" in result.lower()` only echoed the argument the caller passed in.
    again = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "accept"})
    )
    assert again == NO_PENDING, again


async def test_handle_confirm_dismiss(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/dialog")

    await evaluate(
        client, PROFILE, "setTimeout(() => { window._confirmResult = confirm('OK?') }, 0)"
    )

    result = await _answer_dialog(client, "dismiss")
    assert result == "Dialog dismissed", result
    # A dismissed confirm() resolves to false; "dismiss" in the tool's own echo of the
    # argument it was handed could never have proved the dialog was actually answered.
    assert await evaluate(client, PROFILE, "window._confirmResult") == "false"


async def test_handle_prompt(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/dialog")

    await evaluate(
        client, PROFILE, "setTimeout(() => { window._promptResult = prompt('Name?') }, 0)"
    )

    result = await _answer_dialog(client, "accept", prompt_text="Hello from test")
    assert result == "Dialog accepted", result

    stored = await evaluate(client, PROFILE, "window._promptResult")
    assert stored == '"Hello from test"', stored


async def test_handle_dialog_no_pending(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/dialog")

    result = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "accept"})
    )
    assert result == NO_PENDING


async def test_handle_dialog_invalid_action(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/dialog")

    result = tool_text(
        await client.call_tool("handle_dialog", {"profile": PROFILE, "action": "bogus"})
    )
    # The product's one enumeration message: an agent that has met it once knows what
    # to send next, which "error" appearing somewhere in the string never told it.
    assert result == (
        "Error: ValueError: invalid action 'bogus'; valid values: 'accept', 'dismiss'"
    ), result
