"""``get_element(prop='box')``: the geometry half, and the chain into ``click_at``.

Split out of tests/test_get_element.py, which reads properties. A box is only worth
reading if the caller can act on it, so every scenario here ends on a real click at
the point the box named.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, open_page, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

_BOX = re.compile(r"^x=-?\d+ y=-?\d+ w=(\d+) h=(\d+) center=\((-?\d+), (-?\d+)\)$")

# A button far below the fold, plus the viewport height to judge the answer against.
# It reports what it was clicked with, so a coordinate that reaches nothing is not
# mistaken for a coordinate that reached the button.
_ADD_DEEP_BUTTON_JS = """
(() => {
  const spacer = document.createElement('div');
  spacer.style.height = '4000px';
  document.body.appendChild(spacer);
  const deep = document.createElement('button');
  deep.id = 'deep-buy';
  deep.textContent = 'Buy deep';
  deep.addEventListener('click', () => { deep.textContent = 'Bought deep'; });
  document.body.appendChild(deep);
  return window.innerHeight;
})()
"""

# A plain object, not the DOMRect: ``evaluate`` JSON-encodes what it is handed, and a
# DOMRect carries no own enumerable properties to encode.
_RECT_JS = (
    "(() => {{ const r = document.querySelector({selector!r}).getBoundingClientRect();"
    " return {{x: r.x, y: r.y, w: r.width, h: r.height}}; }})()"
)


async def _get(client: Client, **args: object) -> str:
    return tool_text(await client.call_tool("get_element", {"profile": PROFILE, **args}))


async def _rect(client: Client, selector: str) -> dict[str, float]:
    """The element's own viewport rectangle, straight from the page."""
    return json.loads(await evaluate(client, PROFILE, _RECT_JS.format(selector=selector)))


async def test_box_is_usable_as_click_at_coordinates(client: Client, flask_server: str) -> None:
    """The numbers are the element's own rectangle, and its center is clickable.

    ``w > 0 and h > 0`` could not fail on an element the page renders, so it never
    established that the box described THIS element. The page is asked for the same
    rectangle (after the read, which scrolls the element into view) and the rendering
    is compared against the answer.
    """
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#locked", prop="box")

    rect = await _rect(client, "#locked")
    match = _BOX.fullmatch(result)
    assert match, result
    width, height, center_x, center_y = (int(group) for group in match.groups())
    assert (width, height) == (round(rect["w"]), round(rect["h"])), (result, rect)
    assert (center_x, center_y) == (
        round(rect["x"] + rect["w"] / 2),
        round(rect["y"] + rect["h"] / 2),
    ), (result, rect)
    clicked = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": center_x, "y": center_y})
    )
    assert clicked.startswith("Clicked at")


async def test_box_below_the_fold_is_a_point_click_at_can_reach(
    client: Client, flask_server: str
) -> None:
    """The advertised chain, on the case that used to break it silently.

    A box measured where the element sits in the document names a point outside the
    viewport, and `click_at` then reports success having clicked nothing at all. The
    element has to be scrolled into view before it is measured for either half of
    the chain to mean anything.
    """
    await open_page(client, f"{flask_server}/get-element")
    height = int(json.loads(await evaluate(client, PROFILE, _ADD_DEEP_BUTTON_JS)))

    result = await _get(client, selector="#deep-buy", prop="box")

    match = _BOX.fullmatch(result)
    assert match, result
    _, _, center_x, center_y = (int(group) for group in match.groups())
    assert 0 <= center_y <= height, f"center y {center_y} is outside a {height}px viewport"
    clicked = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": center_x, "y": center_y})
    )
    assert clicked.startswith("Clicked at"), clicked
    landed = await text_content(client, PROFILE, "deep-buy")
    assert json.loads(landed) == "Bought deep", landed
