"""The selector wait is bounded, and the bound has to be visible to the caller.

Resolving a selector used to go through the driver, which retried for 30000 ms. The
Python poll that replaced it retries for 5 s, which is the right default (a wrong
selector is far more common than a page that renders 30 s late) and the wrong secret:
a page that builds its form after the budget now fails with a message that reads as
"your selector is wrong", and an agent told that goes and edits a selector that was
already correct.

So two things are pinned here. A late element must still be reachable, through the
tool that owns an unbounded per-call wait. And the expiry message must say which wait
expired, and must not say the same thing when the element was never in the document
as when it was there all along and never became visible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, call_within, evaluate, open_page, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# A guardrail, not a measurement: 4 times the 5s budget under test, so only a wait
# that went unbounded again reaches it.
_GUARDRAIL_S = 20.0

# Comfortably past the 5 s default, and comfortably inside the wait_for timeout below,
# so neither side of the assertion depends on how fast this machine is.
_APPEARS_AFTER_MS = 8000
_WAIT_FOR_MS = 20000

_SCHEDULE_LATE_BUTTON = """() => {
  const host = document.getElementById('host');
  setTimeout(function () {
    const button = document.createElement('button');
    button.id = 'slow-btn';
    button.textContent = 'Slow button';
    button.addEventListener('click', function () {
      document.getElementById('late-output').textContent = 'slow button clicked';
    });
    host.appendChild(button);
  }, __DELAY__);
  return 'scheduled';
}""".replace("__DELAY__", str(_APPEARS_AFTER_MS))

_ADD_HIDDEN_BUTTON = """() => {
  const host = document.getElementById('host');
  const button = document.createElement('button');
  button.id = 'ghost-btn';
  button.textContent = 'Ghost';
  button.style.display = 'none';
  host.appendChild(button);
  return 'added';
}"""


async def _click(client: Client, selector: str) -> str:
    return tool_text(await client.call_tool("click", {"profile": PROFILE, "selector": selector}))


async def test_a_late_element_is_reachable_by_asking_for_a_longer_wait(
    client: Client, flask_server: str
) -> None:
    """The default gives up, and the caller has a documented way to wait longer."""
    await open_page(client, f"{flask_server}/waiting")
    assert "scheduled" in await evaluate(client, PROFILE, _SCHEDULE_LATE_BUTTON)

    gave_up = await call_within(
        client, "click", {"profile": PROFILE, "selector": "#slow-btn"}, _GUARDRAIL_S
    )

    # Giving up at all is the proof the budget held: the button appears after 8s, so a
    # poll that ran that long would have clicked it instead of reporting nothing. The
    # message names the budget, and the guardrail above catches a wait gone unbounded,
    # which is what "elapsed < 10" was standing in for.
    assert gave_up.startswith("Error: ValueError: no element matches selector '#slow-btn'"), gave_up
    assert "5s wait" in gave_up, gave_up
    assert "wait_for(condition='selector'" in gave_up, gave_up

    waited = tool_text(
        await client.call_tool(
            "wait_for",
            {
                "profile": PROFILE,
                "condition": "selector",
                "selector": "#slow-btn",
                "timeout": _WAIT_FOR_MS,
            },
        )
    )
    assert waited.startswith("Condition met: selector"), waited

    clicked = await _click(client, "#slow-btn")
    assert clicked.startswith("Clicked <button>"), clicked
    assert "slow button clicked" in await text_content(client, PROFILE, "late-output")


async def test_never_matched_and_never_visible_read_differently(
    client: Client, flask_server: str
) -> None:
    """One says fix the selector, the other says the element is there but not shown."""
    await open_page(client, f"{flask_server}/waiting")
    assert "added" in await evaluate(client, PROFILE, _ADD_HIDDEN_BUTTON)

    never = await _click(client, "#not-in-this-document")
    hidden = await _click(client, "#ghost-btn")

    assert never != hidden, never
    assert "nothing matched" in never, never
    assert "#ghost-btn" not in never

    assert "matched 1 element but none became visible" in hidden, hidden
    assert "nothing matched" not in hidden, hidden

    for message in (never, hidden):
        assert "5s wait" in message, message
        assert "wait_for(condition='selector'" in message, message
