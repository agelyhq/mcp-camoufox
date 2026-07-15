from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import file_input_selector, resolve_uid_or_raise
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def upload_file(profile: str, uid: str, file_path: str) -> str:
        """Set a file on a file-input associated with a snapshot uid.

        The uid may point at the ``<input type=file>`` itself or at a label/button that
        controls one; the underlying file input is resolved automatically. Take a
        ``snapshot`` first to obtain uids.

        Parameters:
        - profile: session/profile name.
        - uid: uid of the file input (or its trigger) from the latest snapshot.
        - file_path: absolute path to the local file to upload.

        Returns a confirmation like ``Uploaded <path> to <uid>``.

        Errors:
        - ``Error: ValueError: unknown or stale uid '<uid>'; take a new snapshot`` when
          the uid is invalid or stale.
        - ``Error: ValueError: no file input found for uid '<uid>'`` when no file input
          can be resolved.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        await resolve_uid_or_raise(page, uid)
        resolved = await file_input_selector(page, uid)
        if "error" in resolved:
            raise ValueError(f"no file input found for uid '{uid}'")
        selector = resolved.get("selector")
        if not selector:
            raise ValueError(f"no file input found for uid '{uid}'")
        await page.raw.set_input_files(str(selector), file_path)
        return f"Uploaded {file_path} to {uid}"
