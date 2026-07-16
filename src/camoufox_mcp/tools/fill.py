from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import fill_field
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import observe_suffix, validate_observe

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def fill(
        profile: str,
        uid: str | None = None,
        selector: str | None = None,
        *,
        value: str,
        clear_first: bool = True,
        observe: str = "none",
    ) -> str:
        """Type text into an input, textarea or contenteditable, by uid or selector.

        Provide EXACTLY ONE of ``uid`` or ``selector`` (both or neither raises). The
        uid path focuses the snapshot element and types; the selector path is
        Playwright-native and fills the FIRST match.

        Parameters:
        - profile: session/profile name.
        - uid: uid of the field from the latest snapshot. Take a ``snapshot`` first.
        - selector: CSS selector; the first match wins (``locator(selector).first``).
          Prefer this when you already know the field's selector, e.g.
          ``selector="#email"``.
        - value: text to enter (required).
        - clear_first: when true (default) the existing content is cleared before
          typing; when false the value is appended after the current content.
        - observe: post-action observation appended to the result — ``"none"``
          (default), ``"snapshot"`` (fresh uid tree; refreshes uids like calling
          ``snapshot``) or ``"text"`` (page body innerText, capped at 4000 chars).
          Example: ``observe="text"`` to fill then read back the rendered page.

        Returns a confirmation like ``Filled <input> with 12 chars`` (uid) or
        ``Filled #email with 12 chars`` (selector), optionally followed by the
        observation block.

        Errors:
        - ``Error: ValueError: provide exactly one of uid or selector``.
        - ``Error: ValueError: invalid observe '<v>'; ...`` for an unknown observe.
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot``.
        - ``Error: ValueError: element <tag> is not editable; ...`` (uid path) when
          the target is not an input, textarea, select or contenteditable element.
        """
        validate_observe(observe)
        if (uid is None) == (selector is None):
            raise ValueError("provide exactly one of uid or selector")
        session = await get_session(deps, profile)
        page = get_page(session)
        if uid is not None:
            result = await fill_field(page, uid, value, clear_first)
        else:
            locator = page.raw.locator(selector).first
            if clear_first:
                await locator.fill(value)
            else:
                await locator.focus()
                await locator.press_sequentially(value)
            result = f"Filled {selector} with {len(value)} chars"
        return result + await observe_suffix(page, observe)
