from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions.page import DIALOG_ACTIONS
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._errors import validate_choice

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

# The past tense is mapped, never built by string arithmetic on the action: "accept"
# and "dismiss" happen to take "ed", and a third action would silently not.
_ANSWERED = {"accept": "Dialog accepted", "dismiss": "Dialog dismissed"}


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def handle_dialog(profile: str, action: str, prompt_text: str | None = None) -> str:
        """Respond to a pending JavaScript dialog: alert, confirm, prompt, beforeunload.

        A dialog is captured automatically and blocks the page until answered here.

        Args:
            action: "accept" or "dismiss".
            prompt_text: Text submitted to a prompt dialog when accepting.
        """
        validate_choice("action", action, DIALOG_ACTIONS)
        session = await get_session(deps, profile)
        page = get_page(session)
        await page.respond_to_dialog(action, prompt_text)
        return _ANSWERED[action]
