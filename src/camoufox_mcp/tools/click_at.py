from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import ObserveMode, validate_observe

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def _format_points(points: list[list[float]]) -> str:
    return " ".join(f"({round(x)},{round(y)})" for x, y in points)


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def click_at(
        profile: str,
        x: float | None = None,
        y: float | None = None,
        points: list[list[float]] | None = None,
        double_click: bool = False,
        observe: ObserveMode = "none",
    ) -> str:
        """Click raw viewport coordinates, for a canvas, a map or anything without a uid.

        Coordinates are CSS pixels from the viewport top-left. Give exactly 1 of
        (``x`` and ``y``) or ``points``.

        Args:
            points: ``[x, y]`` pairs clicked in order, each at its ORIGINAL
                coordinate with no re-measurement, so a batch is unsafe on a layout
                that reflows between clicks.
            observe: Applied once, after the last click of a batch.
        """
        validate_observe(observe)
        batch = _resolve_points(x, y, points)
        session = await get_session(deps, profile)
        page = get_page(session)
        count = 2 if double_click else 1
        for px, py in batch:
            await page.raw.mouse.click(px, py, click_count=count)
        return _describe(batch, double_click)


def _resolve_points(
    x: float | None, y: float | None, points: list[list[float]] | None
) -> list[list[float]]:
    single = x is not None and y is not None
    if single == (points is not None):
        raise ValueError("provide exactly one of (x and y) or points")
    if points is not None:
        return [[float(px), float(py)] for px, py in points]
    return [[float(x), float(y)]]


def _describe(batch: list[list[float]], double_click: bool) -> str:
    verb = "Double-clicked" if double_click else "Clicked"
    if len(batch) == 1:
        x, y = batch[0]
        return f"{verb} at ({round(x)}, {round(y)})"
    return f"{verb} {len(batch)} points at {_format_points(batch)}"
