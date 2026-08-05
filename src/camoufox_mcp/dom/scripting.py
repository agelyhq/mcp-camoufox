from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom.errors import DeadContextError, raise_for, stale_uid
from camoufox_mcp.dom.waiting import EVAL_TIMEOUT

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import RegistryPage


async def evaluate_with_uids(page: RegistryPage, script: str, uids: list[str]) -> Any:
    """Run a caller-supplied function against live elements named by uid.

    One round trip, so there is no window between checking the uids and running the
    script, and the script is never re-executed. The elements arrive as separate
    positional arguments, so the documented ``(a, b) => ...`` form works. The source
    travels as a protocol argument and is never interpolated into our own code, so
    a syntax error can never name a wrapper the caller did not write.
    """
    try:
        envelope = await page.elements.call(
            "evaluate", {"src": script, "ids": list(uids)}, timeout=EVAL_TIMEOUT
        )
    except DeadContextError as exc:
        raise ValueError(stale_uid(uids[0] if uids else "")) from exc

    if not isinstance(envelope, dict):
        raise ValueError(f"page script returned {type(envelope).__name__}")
    if not envelope.get("ok"):
        raise_for(envelope, str(envelope.get("id", "")), op="evaluate")
    return envelope.get("value")
