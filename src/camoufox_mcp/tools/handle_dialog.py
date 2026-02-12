from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def handle_dialog(action: str, ctx: Context, prompt_text: str | None = None) -> str:
        """Handle a browser dialog (alert, confirm, prompt).

        Args:
            action: 'accept' or 'dismiss'
            prompt_text: Text to enter for prompt dialogs (optional)
        """
        try:
            if action not in ("accept", "dismiss"):
                return "Error: action must be 'accept' or 'dismiss'"

            page = get_page(ctx)
            info = page.get_dialog_info()
            if info is None:
                return "Error: No dialog is currently pending"

            dialog_type = info["type"]
            dialog_message = info["message"]

            await page.respond_to_dialog(action, prompt_text)

            return f"Dialog {action}ed — type: {dialog_type}, message: {dialog_message!r}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
