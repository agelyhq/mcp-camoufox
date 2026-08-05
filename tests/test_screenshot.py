from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

from PIL import Image as PILImage

from tests.helpers import PROFILE, evaluate, extract_uid, goto_and_find, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


def _decode_image(content: object) -> PILImage.Image:
    """Open the base64 PNG carried by an image content block."""
    return PILImage.open(io.BytesIO(base64.b64decode(content.data)))


def _size(content: object) -> tuple[int, int]:
    """Decode the block and return the real PNG dimensions.

    ``len(content.data) > 100`` accepted any 100 base64 characters, so it never
    established that a PNG was produced at all, let alone one with pixels in it.
    """
    assert content.type == "image"
    with _decode_image(content) as img:
        assert img.format == "PNG", img.format
        return img.size


async def test_screenshot_viewport(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    result = await client.call_tool("screenshot", {"profile": PROFILE})

    width, height = _size(result.content[0])
    assert width > 0 and height > 0


async def test_screenshot_full_page(client: Client, flask_server: str) -> None:
    """A full-page capture is taller than the viewport one: the page scrolls."""
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    viewport = await client.call_tool("screenshot", {"profile": PROFILE})
    result = await client.call_tool("screenshot", {"profile": PROFILE, "full_page": True})

    _, viewport_h = _size(viewport.content[0])
    width, height = _size(result.content[0])
    assert width > 0
    assert height > viewport_h, f"full_page height {height} did not exceed {viewport_h}"


async def test_screenshot_element(client: Client, flask_server: str) -> None:
    """An element capture is bounded by the element, not by the viewport."""
    uid = await goto_and_find(client, f"{flask_server}/screenshot", PROFILE, "Index")

    viewport = await client.call_tool("screenshot", {"profile": PROFILE})
    result = await client.call_tool("screenshot", {"profile": PROFILE, "uid": uid})

    viewport_w, viewport_h = _size(viewport.content[0])
    width, height = _size(result.content[0])
    assert 0 < width < viewport_w, f"element width {width} vs viewport {viewport_w}"
    assert 0 < height < viewport_h, f"element height {height} vs viewport {viewport_h}"


async def test_screenshot_max_width_downscales(client: Client, flask_server: str) -> None:
    """A max_width below the capture width returns [note, image] and shrinks it."""
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    base = await client.call_tool("screenshot", {"profile": PROFILE})
    with _decode_image(base.content[0]) as base_img:
        base_w, base_h = base_img.size

    target = base_w // 2
    result = await client.call_tool("screenshot", {"profile": PROFILE, "max_width": target})

    # Mixed content: a text note first, then the downscaled image.
    assert len(result.content) == 2
    note = result.content[0]
    assert note.type == "text"
    assert "scaled" in note.text
    assert f"({base_w}x{base_h} -> {target}x" in note.text
    assert "multiply image coordinates by" in note.text

    image = result.content[1]
    assert image.type == "image"
    with _decode_image(image) as shrunk:
        assert shrunk.width == target
        assert shrunk.height < base_h


async def test_screenshot_max_width_noop_when_not_wider(client: Client, flask_server: str) -> None:
    """A max_width at/above the capture width returns the bare image, unscaled."""
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    base = await client.call_tool("screenshot", {"profile": PROFILE})
    result = await client.call_tool("screenshot", {"profile": PROFILE, "max_width": 100000})

    assert len(result.content) == 1
    # Not merely "an image came back": the pixels must be untouched by the no-op.
    assert _size(result.content[0]) == _size(base.content[0])


ARM_STYLE_OBSERVER_JS = """
(() => {
  window.__styles = [];
  new MutationObserver((records) => {
    records.forEach((r) => window.__styles.push(r.type + ':' + (r.attributeName || '')));
  }).observe(document.documentElement,
             { attributes: true, subtree: true, attributeFilter: ['style'] });
  return 1;
})()
"""


async def test_screenshot_writes_no_style(client: Client, flask_server: str) -> None:
    """Every capture passes caret="initial".

    Without it the driver sets and restores an inline `caret-color` on every input,
    textarea and contenteditable before each shot, which a page reads as attribute
    mutations on its own fields.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/fill", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    uid = extract_uid(snap, "Name")
    assert await evaluate(client, PROFILE, ARM_STYLE_OBSERVER_JS) == "1"

    await client.call_tool("screenshot", {"profile": PROFILE})
    await client.call_tool("screenshot", {"profile": PROFILE, "full_page": True})
    await client.call_tool("screenshot", {"profile": PROFILE, "uid": uid})

    assert await evaluate(client, PROFILE, "window.__styles.length") == "0"
