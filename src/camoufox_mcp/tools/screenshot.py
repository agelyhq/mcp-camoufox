from __future__ import annotations

import io
from typing import TYPE_CHECKING

from fastmcp.utilities.types import Image
from PIL import Image as PILImage

from camoufox_mcp.dom import resolve
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def screenshot(
        profile: str,
        full_page: bool = False,
        uid: str | None = None,
        max_width: int | None = None,
    ) -> Image | list[str | Image]:
        """Capture a PNG of the active tab's viewport. The only tool returning an image.

        Args:
            full_page: Capture the whole scrollable page. Ignored with ``uid``.
            uid: Crop to that element's box, scrolling it into view first.
            max_width: Downscale a wider capture to this width, aspect ratio kept.
                The tool then returns ``[note, image]``, the note carrying the factor
                to multiply image coordinates by before ``click_at``. 0 or less means
                no downscaling, same as omitting it.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        if uid is not None:
            hit = await resolve(page, uid)
            clip = {"x": hit.left, "y": hit.top, "width": hit.width, "height": hit.height}
            # caret="initial" stops the driver writing an inline caret-color onto
            # every field before capturing; the clip is viewport-relative, which is
            # what the non-fullPage path expects.
            png = await page.raw.screenshot(type="png", clip=clip, caret="initial")
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
