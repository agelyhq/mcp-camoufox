"""The 2 read-only page operations: snapshot the tree, or search it.

One convention for both, and the same one the page side already uses: a non-positive
cap (``max_nodes``, ``limit``) means no cap at all. Clamping it to 1 instead would make
"give me everything" silently mean "give me one", which is the opposite answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom.errors import DeadContextError, raise_for

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import RegistryPage

# The capture's own defaults, named so the `snapshot` tool and the post-action
# observation both spend them from one place instead of restating them.
DEFAULT_MAX_NODES = 1500
DEFAULT_INTERACTIVE_ONLY = True


async def capture_snapshot(
    page: RegistryPage,
    max_nodes: int = DEFAULT_MAX_NODES,
    interactive_only: bool = DEFAULT_INTERACTIVE_ONLY,
) -> str:
    """Snapshot the active page as an indented uid tree, capped at ``max_nodes``.

    A uid names an element, not a position: an element still present in the next
    capture of the same document keeps the uid it already had, whatever moved
    around it. Only a cross-document navigation renumbers. When more nodes exist
    than ``max_nodes``, whole trailing nodes are dropped (never a partial line) and
    a truncation note is appended. ``interactive_only`` (the default) drops
    structural nodes with no interactive descendant. ``max_nodes <= 0`` disables the
    cap.
    """
    result = await _read(
        page, "capture", {"maxNodes": max_nodes, "interactiveOnly": interactive_only}
    )
    raise_for(result, "snapshot", op="capture")

    tree = str(result.get("tree", ""))
    if result.get("truncated"):
        overflow = int(result.get("totalNodes", 0)) - int(result.get("shownNodes", 0))
        # Suggesting interactive_only once it is already on would send the caller
        # round a loop that changes nothing.
        hint = "raise max_nodes" if interactive_only else "raise max_nodes or use interactive_only"
        tree += f"\n[truncated: {overflow} more nodes, {hint}]"
    return tree


async def find_elements(
    page: RegistryPage,
    *,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    css: str | None = None,
    limit: int = 10,
) -> str:
    """Search the page for elements and render them as snapshot lines.

    Every filter given must hold. uids come from the same mint the snapshot walk
    uses, so a uid from here and a uid from a snapshot are the same uid for the same
    element. ``limit <= 0`` disables the cap, as ``max_nodes <= 0`` does above.
    """
    if not any((role, name, text, css)):
        raise ValueError("find needs at least one of role, name, text or css")
    arg: dict[str, Any] = {
        "role": role or None,
        "name": name or None,
        "text": text or None,
        "selector": css or None,
        "visible": True,
        "limit": limit,
        "lines": True,
    }
    result = await _read(page, "locate", arg)
    raise_for(result, css or name or text or role or "", op="locate")

    lines = [str(line) for line in result.get("lines", [])]
    header = f"[found {result.get('shown', 0)}/{result.get('total', 0)}]"
    if not lines:
        return f"{header} no element matches"
    return "\n".join([header, *lines])


async def _read(page: RegistryPage, op: str, arg: dict[str, Any]) -> dict[str, Any]:
    """Run a pure read, rebuilding the store once if the document changed.

    Re-running is correct here and only here: both callers read a fresh document
    and have no side effect to replay.
    """
    try:
        result = await page.elements.call(op, arg)
    except DeadContextError:
        try:
            result = await page.elements.call(op, arg)
        except DeadContextError as exc:
            # The internal type must never reach a tool result.
            raise ValueError("the page kept changing while it was read; try again") from exc
    if not isinstance(result, dict):
        raise ValueError(f"page script returned {type(result).__name__} for '{op}'")
    return result
