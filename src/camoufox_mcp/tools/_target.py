"""How a tool turns "which element" into the one uid it will act on.

Two addresses reach the same element: a uid from a snapshot, or a CSS selector bound
to a uid on the spot. Exactly one of them is allowed, and the rejection reads the same
whichever tool asked, because an agent that has learned it once has learned it for all
of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import bind_selector
from camoufox_mcp.tools._target_notes import note_target

if TYPE_CHECKING:
    from camoufox_mcp.dom import RegistryPage

_EXACTLY_ONE = "provide exactly one of uid or selector"


def require_one_target(uid: str | None, selector: str | None) -> None:
    """Reject neither address and both, for a tool that resolves them itself."""
    if (uid is None) == (selector is None):
        raise ValueError(_EXACTLY_ONE)


async def resolve_target(
    page: RegistryPage, uid: str | None, selector: str | None, *, visible: bool = True
) -> str:
    """The uid to act on, binding the selector to one when that is what was given.

    The address is noted here, for both arms and before either does any page work, so
    the record says what a call was aiming at even when nothing matched. What the
    element turns out to BE is attached later, by the caller holding the hit its own
    ``resolve`` already measured.

    ``visible`` reaches the selector arm only: a uid is already minted. The one tool
    that passes ``False`` is ``upload_file``, whose target is hidden by design.
    """
    require_one_target(uid, selector)
    note_target(uid=uid, selector=selector)
    if uid is not None:
        return uid
    return await bind_selector(page, str(selector), visible=visible)
