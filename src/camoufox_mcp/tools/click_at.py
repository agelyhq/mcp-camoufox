from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import observe_suffix, validate_observe

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
        observe: str = "none",
    ) -> str:
        """Click at raw viewport coordinates (bypasses the uid system).

        Use this for canvas, maps or any target that a snapshot cannot address with a
        uid. Coordinates are in CSS pixels relative to the visible viewport top-left.

        Provide EXACTLY ONE of: both ``x`` and ``y`` (a single click), or ``points``
        (a batch). Anything else raises.

        WARNING: batch clicking is unsafe on layouts that shift between clicks — each
        point is clicked at its ORIGINAL coordinate with no re-measurement, so if a
        click reflows the page (expanding/collapsing rows, inserting content) the
        later coordinates may land on the wrong target. Safe on a static canvas or
        fixed grid; risky on collapsible/accordion UIs.

        Parameters:
        - profile: session/profile name.
        - x, y: viewport coordinates in CSS pixels for a single click.
        - points: list of ``[x, y]`` pairs clicked sequentially in order, e.g.
          ``points=[[10, 20], [10, 60], [10, 100]]``.
        - double_click: when true, each click is a double click.
        - observe: post-action observation appended to the result — ``"none"``
          (default), ``"snapshot"`` (fresh uid tree; refreshes uids like calling
          ``snapshot``) or ``"text"`` (page body innerText, capped at 4000 chars).
          For a batch it is applied ONCE, after the last click.

        Returns ``Clicked at (x, y)`` for a single click, or
        ``Clicked 3 points at (x1,y1) (x2,y2) (x3,y3)`` for a batch, optionally
        followed by the observation block.

        Errors:
        - ``Error: ValueError: provide exactly one of (x and y) or points``.
        - ``Error: ValueError: invalid observe '<v>'; ...`` for an unknown observe.
        """
        validate_observe(observe)
        batch = _resolve_points(x, y, points)
        session = await get_session(deps, profile)
        page = get_page(session)
        count = 2 if double_click else 1
        for px, py in batch:
            await page.raw.mouse.click(px, py, click_count=count)
        result = _describe(batch, double_click)
        return result + await observe_suffix(page, observe)


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
