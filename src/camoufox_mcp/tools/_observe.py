from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import capture_snapshot
from camoufox_mcp.tools._errors import error_detail
from camoufox_mcp.tools._text import truncate_chars

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import EvaluatablePage

# Post-action observation modes shared by click, click_at, fill (and navigate).
# "screenshot" is deliberately excluded to preserve the invariant that screenshot
# is the sole image-returning tool.
VALID_OBSERVE = ("none", "snapshot", "text")

_TEXT_MAX_CHARS = 4000
_SNAPSHOT_HEADER = "\n\n--- observation (snapshot) ---\n"
_TEXT_HEADER = "\n\n--- observation (text) ---\n"


def validate_observe(mode: str) -> None:
    """Reject any observe mode outside ``VALID_OBSERVE``.

    Call this once at the top of a tool body (before the side-effecting action) so
    an invalid mode never performs a click/fill. Raises ``ValueError`` listing the
    valid values, which the ``@tool`` wrapper renders as the one-line error string.
    """
    if mode not in VALID_OBSERVE:
        raise ValueError(
            f"invalid observe '{mode}'; valid values: {', '.join(map(repr, VALID_OBSERVE))}"
        )


async def observe_suffix(page: EvaluatablePage, mode: str) -> str:
    """Return the observation block to append after an action, or "" for "none".

    - ``"snapshot"`` reruns the exact ``snapshot`` capture path (default
      max_nodes=1500, interactive_only=False), so it refreshes the uid registry
      exactly as calling the ``snapshot`` tool would — uids from earlier snapshots
      are invalidated and replaced.
    - ``"text"`` returns the page ``body.innerText`` capped at 4000 chars with a
      trailing ``"\\n[truncated N chars]"`` note (same format as get_html).

    Best-effort: the side-effecting action has ALREADY succeeded by the time this
    runs, so an observation failure must never fail the tool (that would invite the
    model to retry the click/fill). Any exception is swallowed and rendered as a
    trailing ``"[observation failed: <error>]"`` note instead of propagating.

    ``mode`` must have already passed ``validate_observe``.
    """
    try:
        if mode == "snapshot":
            return _SNAPSHOT_HEADER + await capture_snapshot(page)
        if mode == "text":
            return _TEXT_HEADER + await _body_text(page)
        return ""
    except Exception as exc:
        return f"\n\n[observation failed: {error_detail(exc)}]"


async def _body_text(page: EvaluatablePage) -> str:
    raw = await page.evaluate("(document.body && document.body.innerText) || ''")
    return truncate_chars(str(raw), _TEXT_MAX_CHARS)
