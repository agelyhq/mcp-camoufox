from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.dom import file_input_selector
from camoufox_mcp.tools._context import get_page


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def upload_file(uid: str, file_path: str, ctx: Context) -> str:
        """Upload a file through a file input element.

        Args:
            uid: Element UID from take_snapshot (must be a file input or contain one)
            file_path: Absolute path to the local file to upload
        """
        try:
            path = Path(file_path)
            if not path.is_absolute():
                return "Error: file_path must be an absolute path"
            if not path.is_file():
                return f"Error: File not found: {file_path}"

            page = get_page(ctx)
            result = await file_input_selector(page, uid)
            if "error" in result:
                return f"Error: {result['error']}"

            await page.set_input_files(result["selector"], file_path)
            return f"Uploaded {path.name} via {uid}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
