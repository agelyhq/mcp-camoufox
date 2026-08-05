from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from camoufox_mcp.dom import capture_snapshot
from camoufox_mcp.tools._errors import error_detail, log_swallowed, validate_choice
from camoufox_mcp.tools._text import truncate_chars, truncation_note

if TYPE_CHECKING:
    from camoufox_mcp.dom import EvaluatablePage, RegistryPage

# Post-action observation modes shared by click, click_at, fill (and navigate).
# "screenshot" is deliberately excluded to preserve the invariant that screenshot
# is the sole image-returning tool.
VALID_OBSERVE = ("none", "snapshot", "text")

# The values a caller may pass, in the schema rather than only in the instructions:
# a client is free never to show the instructions, and an agent that has not seen
# them would otherwise have to guess the 3 words. Validation stays ours
# (``validate_observe``) so a wrong value still returns the product's one-line error
# instead of a framework validation dump.
ObserveMode = Annotated[str, Field(json_schema_extra={"enum": list(VALID_OBSERVE)})]

# Both observations are an appendix to an action's result, not a deliberate capture,
# so they answer to the same budget. Uncapped, "snapshot" returned 35,395 chars from
# 1 navigate on the 4,000-row test page against 72 with observe="none", more than the
# whole tool surface costs to send. A caller that wants the entire tree asks for it
# with `snapshot`, where the cap is a parameter it can raise. Measured by
# tests/test_observe_cost.py.
OBSERVE_MAX_CHARS = 4000

_SNAPSHOT_HEADER = "\n\n--- observation (snapshot) ---\n"
_TEXT_HEADER = "\n\n--- observation (text) ---\n"
# Same shape as every other truncation note in the product: what came back, what
# exists, and the next call. Neither cap is a parameter of the acting tool, so both
# notes send the caller to the tool that owns one rather than to a knob it cannot
# reach from here.
_SNAPSHOT_CAP_FIXED = "This cap is fixed, call snapshot or find for the rest"
_TEXT_CAP_FIXED = "This cap is fixed, call get_html for the full text"


def validate_observe(mode: str) -> None:
    """Reject any observe mode outside ``VALID_OBSERVE``.

    Call this once at the top of a tool body (before the side-effecting action) so
    an invalid mode never performs a click/fill.
    """
    validate_choice("observe", mode, VALID_OBSERVE)


async def observe_suffix(page: RegistryPage, mode: str) -> str:
    """Return the observation block to append after an action, or "" for "none".

    - ``"snapshot"`` reruns the ``snapshot`` capture path with its own defaults
      (max_nodes=1500, interactive_only=True), then caps the tree at
      ``OBSERVE_MAX_CHARS`` on a line boundary: half a line would carry half a uid,
      which reads like a usable uid and is not one.
    - ``"text"`` returns the page ``body.innerText`` under the same cap.

    Neither cap is reachable from the acting tool, so both truncation notes name the
    tool that owns a cap instead of a knob the caller cannot turn.

    Best-effort: the side-effecting action has ALREADY succeeded by the time this
    runs, so an observation failure must never fail the tool (that would invite the
    model to retry the click/fill). Any exception is swallowed and rendered as a
    trailing ``"[observation failed: <error>]"`` note instead of propagating.

    ``mode`` must have already passed ``validate_observe``.
    """
    try:
        if mode == "snapshot":
            return _SNAPSHOT_HEADER + _cap_tree(await capture_snapshot(page))
        if mode == "text":
            return _TEXT_HEADER + await _body_text(page)
        return ""
    except Exception as exc:
        # This block swallows the exception into a note, so it is the ONE tool-side
        # path the @tool wrapper never sees. Issue #13 had an occurrence hidden here
        # (a navigate that reported ok=true with the failure buried in the note), so
        # an off-contract exception must still leave a stack in the server log.
        log_swallowed(f"capturing the '{mode}' observation", exc)
        return f"\n\n[observation failed: {error_detail(exc)}]"


async def _body_text(page: EvaluatablePage) -> str:
    raw = await page.evaluate("(document.body && document.body.innerText) || ''")
    return truncate_chars(str(raw), OBSERVE_MAX_CHARS, _TEXT_CAP_FIXED)


def _cap_tree(tree: str) -> str:
    """Hold the appended tree to ``OBSERVE_MAX_CHARS``, cutting on a line boundary.

    A snapshot line is one element, so the cut is taken at the last newline that
    fits: a half line would hand back a truncated uid, which is indistinguishable
    from a real one until it fails. The note counts characters, because characters
    are what the caller pays for and what the cap is expressed in.
    """
    if len(tree) <= OBSERVE_MAX_CHARS:
        return tree
    head = tree[:OBSERVE_MAX_CHARS]
    kept = head.rsplit("\n", 1)[0] if "\n" in head else head
    return kept + "\n" + truncation_note(len(kept), len(tree), "chars", _SNAPSHOT_CAP_FIXED)
