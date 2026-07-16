from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

from PIL import Image as PILImage

from tests.helpers import PROFILE, goto_and_find

if TYPE_CHECKING:
    from fastmcp import Client


def _decode_image(content: object) -> PILImage.Image:
    """Open the base64 PNG carried by an image content block."""
    return PILImage.open(io.BytesIO(base64.b64decode(content.data)))


async def test_screenshot_viewport(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    result = await client.call_tool("screenshot", {"profile": PROFILE})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100


async def test_screenshot_full_page(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    result = await client.call_tool("screenshot", {"profile": PROFILE, "full_page": True})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100


async def test_screenshot_element(client: Client, flask_server: str) -> None:
    uid = await goto_and_find(client, f"{flask_server}/screenshot", PROFILE, "Index")

    result = await client.call_tool("screenshot", {"profile": PROFILE, "uid": uid})
    content = result.content[0]
    assert content.type == "image"
    assert len(content.data) > 100


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
    """A max_width at/above the capture width returns the bare image, no note."""
    await client.call_tool("navigate", {"url": f"{flask_server}/screenshot", "profile": PROFILE})

    result = await client.call_tool("screenshot", {"profile": PROFILE, "max_width": 100000})

    assert len(result.content) == 1
    assert result.content[0].type == "image"
    assert len(result.content[0].data) > 100
