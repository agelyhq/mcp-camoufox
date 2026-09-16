from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import set_files
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._target import resolve_target
from camoufox_mcp.tools._target_notes import target_analytics

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps, analytics=target_analytics)
    async def upload_file(
        profile: str,
        file_path: str,
        uid: str | None = None,
        selector: str | None = None,
    ) -> str:
        """Attach a local file to a file input, by snapshot uid or by selector.

        Never click a site's "Add media" button: it opens an OS dialog no tool can
        drive. The target may be the ``<input type=file>`` itself, the ``<label>``
        controlling it, or a wrapper containing it; ``selector`` reaches an input
        the site keeps hidden. The file must be at most 25 MB.

        Args:
            file_path: Absolute native path on the machine running this server, e.g.
                C:\\Users\\you\\Pictures\\photo.png, C:/... or /home/you/photo.png;
                surrounding quotes, ~, %VAR% and file:// are accepted. A file
                attached to the chat has no path: ask for one.
            selector: CSS matching the input, e.g. "input[type=file]"; a hidden
                match is accepted.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        target = await resolve_target(page, uid, selector, visible=False)
        return await set_files(page, target, file_path)
