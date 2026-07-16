from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

_VALID_ACTIONS = ("accept", "dismiss")


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def handle_dialog(profile: str, action: str, prompt_text: str | None = None) -> str:
        """Respond to a pending JavaScript dialog (alert / confirm / prompt / beforeunload).

        A dialog raised by the page is captured automatically; call this to accept or
        dismiss it so the page can continue.

        Parameters:
        - profile: session/profile name.
        - action: ``accept`` or ``dismiss``.
        - prompt_text: text to submit for a ``prompt`` dialog when accepting (ignored
          for other dialog types and when dismissing).

        Returns a confirmation like ``Dialog accepted``.

        Errors:
        - ``Error: ValueError: action must be 'accept' or 'dismiss'``.
        - ``Error: RuntimeError: No dialog is pending`` when nothing is waiting.
        """
        if action not in _VALID_ACTIONS:
            raise ValueError(f"action must be {' or '.join(map(repr, _VALID_ACTIONS))}")
        session = await get_session(deps, profile)
        page = get_page(session)
        await page.respond_to_dialog(action, prompt_text)
        return f"Dialog {action}ed"
