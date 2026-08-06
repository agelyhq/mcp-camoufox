"""The 1 page read whose answer is the document rather than an element.

Every other read here is addressed by uid. This one is scoped by selector and returns
markup or rendered text, and it used to be the exception in a second sense too: the
tool built its own script in Python and evaluated it outside the bundle, so
``document.querySelector``, ``cloneNode``, ``querySelectorAll`` and
``NodeList.prototype.forEach`` were resolved on the page's own prototypes at call time.
That made ``strip_scripts`` defeatable rather than merely observable: a page replacing
``forEach`` with a no-op kept its ``<script>`` elements in output a caller had asked to
have none. Routed through the ``extract`` operation, every step goes through the boot
table of ``js/00_boot.js``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom.errors import DeadContextError, raise_for

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import RegistryPage

# The 2 shapes a scope can be serialised into. The page side branches on these same
# words, so the tool validating a caller's ``mode`` spends this tuple instead of
# declaring a second copy that nothing keeps in step with the script.
MARKUP_MODES = ("html", "text")

_OP = "extract"
_KEPT_MOVING = "the page kept changing while it was read; try again"


async def read_markup(
    page: RegistryPage, *, selector: str | None, mode: str, strip_scripts: bool
) -> str:
    """The active document's markup (``mode="html"``) or rendered text, scoped.

    ``selector`` scopes the read to its first match, or to the document element when
    it is ``None``. ``strip_scripts`` drops every ``<script>`` from a clone, so the
    live page is never mutated.

    A selector that matched nothing raises rather than returning the empty string: to
    a caller the 2 are the same answer, and only one of them is actionable.
    """
    arg: dict[str, Any] = {"selector": selector, "mode": mode, "strip": strip_scripts}
    result = await _read(page, arg)
    raise_for(result, selector or "", op=_OP)
    if not result.get("found"):
        raise ValueError(f"no element matches selector '{selector}'")
    return str(result.get("value", ""))


async def _read(page: RegistryPage, arg: dict[str, Any]) -> dict[str, Any]:
    """Run the read, rebuilding the store once if the document changed under it.

    Re-running is correct for the reason it is correct in ``capture.py``: this read
    has no side effect to replay. The internal dead-context type must never reach a
    tool result, so the second failure becomes a message the caller can act on.
    """
    try:
        result = await page.elements.call(_OP, arg)
    except DeadContextError:
        try:
            result = await page.elements.call(_OP, arg)
        except DeadContextError as exc:
            raise ValueError(_KEPT_MOVING) from exc
    if not isinstance(result, dict):
        raise ValueError(f"page script returned {type(result).__name__} for '{_OP}'")
    return result
