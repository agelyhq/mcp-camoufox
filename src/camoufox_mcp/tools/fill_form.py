from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import fill_field
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._errors import collapse_message, is_unexpected

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.dom import ActionablePage
    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def fill_form(profile: str, fields: list[dict[str, str]]) -> str:
        """Fill several fields in 1 call, each focused, cleared and filled in order.

        Args:
            fields: Objects ``{"uid": "eN", "value": "text"}``.
        """
        pairs = _validated(fields)
        session = await get_session(deps, profile)
        page = get_page(session)
        for index, (uid, value) in enumerate(pairs):
            await _fill_one(page, index, uid, value)
        return f"Filled {len(pairs)} field(s)"


def _validated(fields: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Every field checked before the first one is written.

    Validating inside the loop left the page half filled by a call that then failed,
    which is the worst of both outcomes: the agent cannot tell what landed, and a
    retry re-types the fields that already had.
    """
    pairs: list[tuple[str, str]] = []
    for index, field in enumerate(fields):
        uid = field.get("uid")
        value = field.get("value")
        if not uid or value is None:
            raise ValueError(f"field {index} needs 'uid' and 'value'")
        pairs.append((uid, value))
    return pairs


async def _fill_one(page: ActionablePage, index: int, uid: str, value: str) -> None:
    """Fill one field, naming which one when it fails, without erasing what failed.

    A bare "unknown or stale uid" out of a 6-field call says nothing about which of
    the 6 was wrong, and the agent has no way to find out short of retrying them one
    at a time. So the position is added, and nothing else is: catching every exception
    and re-raising ``ValueError`` cost 2 things this contract owes. A ``TimeoutError``
    rendered as "Error: ValueError" instead of the mandated "Timeout: ...", and an
    off-contract type stopped leaving a traceback in the server log, which is the exact
    shape that left a 133-occurrence ``UnicodeDecodeError`` unexplained for a month.

    Only a rejected value is annotated, therefore, and only when the funnel that
    decides what earns a traceback says it is on contract. The message is rewritten in
    place on the original exception rather than into a new one of the same class: a
    ``ValueError`` subclass need not take a single string (``UnicodeDecodeError``
    itself does not), and a ``TypeError`` raised while handling the real failure would
    replace the diagnostic with its own. ``raise`` then re-raises the very object,
    class and traceback included.
    """
    try:
        await fill_field(page, uid, value)
    except ValueError as exc:
        if is_unexpected(exc):
            raise
        exc.args = (f"field {index} (uid '{uid}'): {collapse_message(str(exc))}",)
        raise
