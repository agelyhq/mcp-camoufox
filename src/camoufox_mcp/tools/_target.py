"""How a tool turns "which element" into the one uid it will act on.

Two addresses reach the same element: a uid from a snapshot, or a CSS selector bound
to a uid on the spot. Exactly one of them is allowed, and the rejection reads the same
whichever tool asked, because an agent that has learned it once has learned it for all
of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import bind_selector

if TYPE_CHECKING:
    from camoufox_mcp.dom import RegistryPage

_EXACTLY_ONE = "provide exactly one of uid or selector"


def require_one_target(uid: str | None, selector: str | None) -> None:
    """Reject neither address and both, for a tool that resolves them itself."""
    if (uid is None) == (selector is None):
        raise ValueError(_EXACTLY_ONE)


async def resolve_target(page: RegistryPage, uid: str | None, selector: str | None) -> str:
    """The uid to act on, binding the selector to one when that is what was given."""
    require_one_target(uid, selector)
    if uid is not None:
        return uid
    return await bind_selector(page, str(selector))
