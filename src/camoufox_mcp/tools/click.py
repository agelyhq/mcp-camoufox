from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import resolve_center
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import observe_suffix, validate_observe

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def click(
        profile: str,
        uid: str | None = None,
        selector: str | None = None,
        double_click: bool = False,
        observe: str = "none",
    ) -> str:
        """Click an element, addressed by snapshot uid or by CSS selector.

        Provide EXACTLY ONE of ``uid`` or ``selector`` (both or neither raises).
        The uid path scrolls the snapshot element into view and clicks its center;
        the selector path is Playwright-native and clicks the FIRST match.

        Parameters:
        - profile: session/profile name.
        - uid: element uid from the latest snapshot (e.g. ``e12``). Take a
          ``snapshot`` first to obtain uids.
        - selector: CSS selector; the first match wins (``locator(selector).first``).
          Prefer this when you already know the element's selector, e.g.
          ``selector="#submit"``.
        - double_click: when true, performs a double click instead of a single click.
        - observe: post-action observation appended to the result. ``"none"``
          (default) appends nothing; ``"snapshot"`` appends a fresh snapshot
          (refreshes uids exactly like calling ``snapshot`` — earlier uids become
          stale); ``"text"`` appends the page body innerText (capped at 4000 chars).
          Example: ``observe="snapshot"`` to click then re-read uids in one call.

        Returns a confirmation like ``Clicked <button> at (x, y)`` (uid) or
        ``Clicked #submit`` (selector), optionally followed by the observation block.

        Errors:
        - ``Error: ValueError: provide exactly one of uid or selector``.
        - ``Error: ValueError: invalid observe '<v>'; ...`` for an unknown observe.
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot``.
        """
        validate_observe(observe)
        if (uid is None) == (selector is None):
            raise ValueError("provide exactly one of uid or selector")
        session = await get_session(deps, profile)
        page = get_page(session)
        verb = "Double-clicked" if double_click else "Clicked"
        if uid is not None:
            x, y, tag = await resolve_center(page, uid)
            await page.raw.mouse.click(x, y, click_count=2 if double_click else 1)
            result = f"{verb} <{tag}> at ({round(x)}, {round(y)})"
        else:
            locator = page.raw.locator(selector).first
            if double_click:
                await locator.dblclick()
            else:
                await locator.click()
            result = f"{verb} {selector}"
        return result + await observe_suffix(page, observe)
