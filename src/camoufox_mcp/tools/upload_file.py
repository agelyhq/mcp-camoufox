from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import set_files
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def upload_file(profile: str, uid: str, file_path: str) -> str:
        """Attach a local file to a file input addressed by uid.

        The uid may be the ``<input type=file>``, the ``<label>`` controlling it, or a
        styled wrapper: the input is resolved from it. The file must be at most 25 MB.

        Args:
            file_path: Absolute path to the local file.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        return await set_files(page, uid, file_path)
