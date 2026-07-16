from __future__ import annotations

import io
from typing import TYPE_CHECKING

from fastmcp.utilities.types import Image
from PIL import Image as PILImage

from camoufox_mcp.dom import resolve_uid_or_raise, scroll_into_view
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def screenshot(
        profile: str,
        full_page: bool = False,
        uid: str = "",
        max_width: int | None = None,
    ) -> Image | list[str | Image]:
        """Capture a PNG screenshot of the active tab.

        This is the only tool that returns an image rather than text. By default it
        captures the current viewport. Set ``full_page`` to capture the entire
        scrollable page, or pass a ``uid`` to crop to a single element's bounding
        box (from the most recent snapshot).

        Params:
            profile: The browser profile whose active tab is captured.
            full_page: When true, capture the full scrollable page height instead
                of just the visible viewport. Ignored when ``uid`` is given.
            uid: Optional ``eN`` element uid (from ``snapshot``) to crop the shot to
                that element only. The element is scrolled into view first. Leave
                empty to screenshot the page/viewport.
            max_width: Optional pixel cap on the returned image width. When the
                captured image is wider, it is downscaled (aspect ratio preserved)
                to cut image-token cost. In that case the tool returns a two-item
                list ``[note, image]`` where ``note`` reports the scale and the
                factor to multiply image coordinates by before ``click_at`` (the
                image is smaller than the page it represents). When unset, or when
                the capture is already at or below ``max_width``, the bare image is
                returned unchanged. ``max_width <= 0`` disables the cap.

        Returns:
            A PNG image of the requested region, or ``[note, image]`` when the image
            was downscaled to honor ``max_width``.

        Errors (returned as an "Error:"/"Timeout:" string, never raised):
            - "Error: ValueError: unknown or stale uid '<uid>'; take a new
              snapshot" if the uid is missing or stale.
            - "Error: ProfileInUseError: ..." if the profile lock is held.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        if uid:
            await scroll_into_view(page, uid)
            info = await resolve_uid_or_raise(page, uid)
            width = float(info["width"])
            height = float(info["height"])
            clip = {
                "x": float(info["x"]) - width / 2,
                "y": float(info["y"]) - height / 2,
                "width": width,
                "height": height,
            }
            png = await page.raw.screenshot(type="png", clip=clip)
        else:
            png = await page.screenshot(full_page=full_page)
        return _maybe_downscale(png, max_width)


def _maybe_downscale(png: bytes, max_width: int | None) -> Image | list[str | Image]:
    """Return the bare image, or ``[note, image]`` when a downscale was applied.

    A downscale happens only when ``max_width`` is a positive int smaller than the
    captured image's width; otherwise the original PNG bytes are returned untouched
    so the default path stays byte-identical.
    """
    if max_width is None or max_width <= 0:
        return Image(data=png, format="png")

    with PILImage.open(io.BytesIO(png)) as img:
        orig_w, orig_h = img.size
        if orig_w <= max_width:
            return Image(data=png, format="png")
        new_w = max_width
        new_h = max(1, round(orig_h * max_width / orig_w))
        resized = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        scaled_png = buffer.getvalue()

    scale = new_w / orig_w
    multiply = orig_w / new_w
    note = (
        f"scaled {scale:.2f}x ({orig_w}x{orig_h} -> {new_w}x{new_h}); "
        f"multiply image coordinates by {multiply:.2f} before click_at"
    )
    return [note, Image(data=scaled_png, format="png")]
