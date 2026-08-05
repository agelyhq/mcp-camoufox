from __future__ import annotations

from typing import Any

# The mandated string, byte for byte. It now covers four causes: an unknown or
# malformed uid, a detached element, a store rebuilt by navigation, and a dead
# execution context. It stays a plain ValueError so the rendered prefix is
# unchanged.
#
# The placeholder is ``{target}`` like every other template below: the value a
# template receives is whatever the failing call was addressed by, which is a uid here
# but a CSS selector or the word "snapshot" elsewhere. :func:`stale_uid` is the one
# spelling callers use, so no call site has to know that.
STALE_UID = "unknown or stale uid '{target}'; take a new snapshot"


def stale_uid(uid: str) -> str:
    """The mandated stale-uid message for ``uid``."""
    return STALE_UID.format(target=uid)


class ElementInterceptedError(ValueError):
    """A pointer action was blocked by another element covering the target."""


class DeadContextError(RuntimeError):
    """Internal: the page execution context died. Never reaches a tool result.

    Every caller in this package converts it, either to the mandated stale-uid
    string or by rebuilding the store and re-running a pure read.
    """

    def __init__(self, op: str) -> None:
        self.op = op
        super().__init__(f"the page execution context died during '{op}'")


# The driver mints a dedicated exception class for exactly two conditions, a timeout
# and a closed target (``parse_error`` in ``playwright/_impl/_helper.py``). A
# destroyed execution context is not one of them: it arrives as the driver's base
# ``Error`` with ``name == "Error"``, so there is no class to test and a message test
# is the only classifier available. That is why this is the single place in the
# package matching on wording, and the phrases below are literals the driver itself
# throws, not paraphrases: ``ExecutionContext.contextDestroyed`` is called with them
# in ``coreBundle.js`` (:18471 for a detached frame, :18514 and :18522 for a
# navigation) and the Firefox ``rewriteError`` path re-throws the second one (:42817).
#
# Measured on camoufox 0.5.4 / Firefox 152.0.4-beta.28 with playwright 1.60: 12 of 12
# navigation races and the iframe-removal case all produced
# ``Error: JSHandle.evaluate: Execution context was destroyed, most likely because of
# a navigation``, and a closed tab produced ``TargetClosedError`` instead.
_DEAD_CONTEXT_PHRASES = (
    "execution context was destroyed",
    "frame was detached",
)


def is_dead_context(exc: BaseException) -> bool:
    """True when ``exc`` reports that the page's execution context no longer exists.

    Everything else is infrastructure, a protocol hiccup, or a defect of ours, and
    must surface as itself. Reporting those as a stale uid would tell the agent that
    1 element went bad when nothing did, and would justify resetting a uid namespace
    that is still perfectly valid.
    """
    text = str(exc).casefold()
    return any(phrase in text for phrase in _DEAD_CONTEXT_PHRASES)


# One table, one arity. Every entry is a code some page operation actually emits,
# and names only fields that operation is specified to return. Conditions decided in
# Python raise their message directly instead of round-tripping through a code.
#
# ``{target}`` is whatever the failing call was addressed by: a uid for the element
# ops, a CSS selector for ``locate``, the word "snapshot" for ``capture``. The
# templates that can only ever fire on a uid say "uid" in their prose; the placeholder
# itself does not, because it is not always one.
_TEMPLATES: dict[str, str] = {
    "unknown": STALE_UID,
    "zero_size": "uid '{target}' resolves to <{tag}> with zero size; it is present but not rendered",
    "offscreen": "uid '{target}' (<{tag}>) cannot be scrolled into the viewport",
    "disabled": "element <{tag}> for uid '{target}' is disabled",
    "readonly": "element <{tag}> for uid '{target}' is read-only",
    "not_focusable": "element <{tag}> for uid '{target}' could not take focus",
    "not_select": "element <{tag}> for uid '{target}' is not a select",
    "no_option": "uid '{target}' has no option with that value",
    "no_file_input": "no file input found for uid '{target}'",
    "directory_input": (
        "uid '{target}' is a directory input (webkitdirectory); "
        "uploading a directory is not supported"
    ),
    "bad_selector": "invalid selector '{target}': {msg}",
    "syntax": "script is not a valid function expression: {msg}",
    "not_function": (
        "with uids, script must be a function expression, e.g. (a, b) => a.textContent"
    ),
    "script": "script threw: {msg}",
    "internal": "page script failed in '{op}': {msg}",
}


def raise_for(result: Any, target: str, *, op: str) -> None:
    """Raise the typed error for a JS ``{"err": code, ...}`` payload, else return.

    This is the only place JS error codes are decoded. A ``resolve`` payload that
    reports an interception is raised here too, so every consumer of an element
    operation gets the same treatment.

    ``op`` is required rather than defaulted. Three of the messages below report a
    failure inside our own page script, where the operation name is the entire
    diagnostic value, and a default would let a caller drop the one field that says
    which of our operations broke.
    """
    if not isinstance(result, dict):
        raise ValueError(f"page script returned {type(result).__name__} in '{op}' for '{target}'")

    code = result.get("err")
    if code is None:
        intercept = result.get("intercept")
        if intercept:
            _raise_intercepted(result, intercept, target)
        return

    template = _TEMPLATES.get(str(code))
    if template is None:
        raise ValueError(f"page script failed with '{code}' in '{op}' for '{target}'")
    message = template.format(
        target=target,
        tag=result.get("tag", "?"),
        msg=result.get("msg", ""),
        op=op,
    )
    raise ValueError(message)


def _raise_intercepted(hit: dict[str, Any], intercept: dict[str, Any], target: str) -> None:
    at = f"({round(float(hit.get('x', 0)))}, {round(float(hit.get('y', 0)))})"
    subject = str(intercept.get("by", "<unknown>"))
    root = intercept.get("root")
    origin = f" from {root} subtree" if root else ""
    raise ElementInterceptedError(
        f"{subject}{origin} intercepts pointer events on uid '{target}' "
        f"(<{hit.get('tag', '?')}>) at {at}"
    )
