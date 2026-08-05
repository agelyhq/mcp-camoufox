from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, open_and_snapshot, open_page, tool_text
from tests.waits import wait_predicate

if TYPE_CHECKING:
    from fastmcp import Client

SCROLL_Y_JS = "Math.round(window.scrollY)"


def _in_viewport_js(selector: str) -> str:
    """A predicate that is true when the element sits fully inside the viewport.

    That is what "scrolled into view" means; a scrollY delta would also accept a 1 px
    move.
    """
    return f"""
    (() => {{
      const r = document.querySelector({selector!r}).getBoundingClientRect();
      return r.top >= 0 && r.bottom <= window.innerHeight;
    }})()
    """


async def test_scroll_down(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/scroll")

    before = int(await evaluate(client, PROFILE, SCROLL_Y_JS))
    assert before == 0, "the page must start at the top for the delta to mean anything"

    result = tool_text(
        await client.call_tool("scroll", {"profile": PROFILE, "direction": "down", "amount": 600})
    )
    assert "scrolled" in result.lower()

    # The requested amount is the contract, not merely "some movement": a 1 px scroll
    # would satisfy "> 0" while leaving the model's mental model of the page wrong. The
    # predicate is that exact contract, so the wait and the assertion are the same claim.
    await wait_predicate(client, PROFILE, f"{SCROLL_Y_JS} === 600", timeout_ms=5000)
    js = await evaluate(client, PROFILE, SCROLL_Y_JS)
    assert int(js) == 600, f"asked to scroll 600px, landed at {js}"


async def test_scroll_element_into_view(client: Client, flask_server: str) -> None:
    """A page-driven ``scrollIntoView`` lands the element inside the viewport.

    Asserted on the element's rect, which is what "in view" means: ``after > before``
    also passes on a 1 px move.
    """
    await open_page(client, f"{flask_server}/scroll")

    before = int(await evaluate(client, PROFILE, SCROLL_Y_JS))
    assert before == 0, "the page must start at the top for the scroll to prove anything"

    await evaluate(
        client,
        PROFILE,
        "document.getElementById('section-10').scrollIntoView({behavior:'instant'})",
    )

    await wait_predicate(client, PROFILE, _in_viewport_js("#section-10"), timeout_ms=5000)
    after = int(await evaluate(client, PROFILE, SCROLL_Y_JS))
    assert after > before


async def test_scroll_uid_brings_the_element_back_into_view(
    client: Client, flask_server: str
) -> None:
    """``scroll(uid=...)`` is the product's own path and had no test at all.

    The nav link is the page's only element that gets a uid, so it is scrolled off the
    top first (asserted, otherwise the scroll back would prove nothing) and then brought
    back with the tool.
    """
    snap = await open_and_snapshot(client, f"{flask_server}/scroll")
    uid = extract_uid(snap, "Index")

    await client.call_tool("scroll", {"profile": PROFILE, "direction": "down", "amount": 2000})
    await wait_predicate(
        client,
        PROFILE,
        "document.querySelector('.nav a').getBoundingClientRect().bottom < 0",
        timeout_ms=5000,
    )

    result = tool_text(await client.call_tool("scroll", {"profile": PROFILE, "uid": uid}))
    assert result.startswith("Scrolled <"), result

    await wait_predicate(client, PROFILE, _in_viewport_js(".nav a"), timeout_ms=5000)


async def test_scroll_invalid_direction(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/scroll")

    result = tool_text(
        await client.call_tool("scroll", {"profile": PROFILE, "direction": "sideways"})
    )
    assert result == (
        "Error: ValueError: invalid direction 'sideways'; valid values: "
        "'down', 'up', 'left', 'right'"
    ), result
