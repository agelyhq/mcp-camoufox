from __future__ import annotations

import logging
import re

from camoufox_mcp.sessions.errors import (
    PLAYWRIGHT_ERROR,
    PLAYWRIGHT_TIMEOUT_ERROR,
    ProfileInUseError,
)

logger = logging.getLogger(__name__)

# Playwright's base exception class is literally named ``Error`` (``__name__ ==
# "Error"``), which would render as the meaningless "Error: Error: ...". Map the
# bare name to something legible while keeping the real type for every other class.
_BARE_ERROR_ALIAS = "PlaywrightError"

# Everything from this marker onward is Playwright's multi-line action trace; it can
# be thousands of chars and is noise to the model, so it is dropped entirely.
_CALL_LOG_MARKER = "Call log:"

# A JS exception raised in the page arrives with its stack appended, one frame per
# line ("@debugger eval code line 302 > eval:1:15"). Folding those into the message
# hands the model three lines of noise and the source location of code it never
# wrote, so they are dropped before the fold.
_STACK_FRAME = re.compile(r"@(?:debugger eval code|blob:|https?:|file:|moz-extension:)")

# The failure modes every tool docstring documents: a rejected argument, a locked
# profile, or anything Playwright itself raises (its base class covers TimeoutError,
# TargetClosedError and the protocol errors). Anything outside this set is a defect
# in this server or one of its dependencies, and the one-line contract below would
# otherwise erase it without a stack.
_CONTRACT_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,
    TimeoutError,
    ProfileInUseError,
    PLAYWRIGHT_ERROR,
)


def validate_choice(field: str, value: str, allowed: tuple[str, ...]) -> None:
    """Reject a value outside ``allowed``, in the product's one enumeration message.

    Every tool that takes a closed set of words routes through this, so an agent
    that has learned the shape of one rejection has learned all of them. Raises
    ``ValueError``, which the ``@tool`` wrapper renders as the one-line error string.
    """
    if value not in allowed:
        raise ValueError(
            f"invalid {field} '{value}'; valid values: {', '.join(map(repr, allowed))}"
        )


def is_unexpected(exc: BaseException) -> bool:
    """True when ``exc`` falls outside the documented tool error contract.

    Callers use it to decide whether the exception earns a full traceback in the
    server log; the string handed back to the model stays one line either way.
    """
    if isinstance(exc, UnicodeError):
        # UnicodeDecodeError/UnicodeEncodeError subclass ValueError, but no tool
        # ever raises one deliberately: it means a byte payload reached a text-only
        # path. That is exactly the shape behind issue #13, so never let the
        # ValueError branch below absorb it.
        return True
    return not isinstance(exc, _CONTRACT_ERRORS)


def error_type_name(exc: BaseException) -> str:
    """The exception's class name, aliasing Playwright's bare ``Error``."""
    name = type(exc).__name__
    return _BARE_ERROR_ALIAS if name == "Error" else name


def collapse_message(message: str) -> str:
    """Cut the Playwright call log and stack frames, and fold what is left to one line."""
    head = message.split(_CALL_LOG_MARKER, 1)[0]
    lines = [part.strip() for part in head.splitlines() if part.strip()]
    kept = [line for line in lines if not _STACK_FRAME.search(line)]
    # A message made of nothing but frames is still better than an empty string.
    return "; ".join(kept or lines)


def error_detail(exc: BaseException) -> str:
    """One-line ``Type: message`` used for the telemetry ``error`` field."""
    return f"{error_type_name(exc)}: {collapse_message(str(exc))}"


def format_error(exc: BaseException) -> str:
    """Render an exception per the contract: "Timeout: ..." / "Error: Type: msg".

    Playwright errors are collapsed to a single line (call log stripped) and the
    bare ``Error`` type is aliased so the string never reads "Error: Error:".
    """
    if isinstance(exc, (TimeoutError, PLAYWRIGHT_TIMEOUT_ERROR)):
        return f"Timeout: {collapse_message(str(exc))}"
    return f"Error: {error_detail(exc)}"


def log_swallowed(what: str, exc: Exception) -> None:
    """Log an exception that must never reach the caller, with a stack when off contract.

    Everything appended AFTER an action succeeded (the page line, an observation)
    swallows its own failures rather than turning a successful click into an error
    string. That makes those paths the kind of place a defect hides in for weeks,
    which is what happened to issue #13, so anything outside the error contract still
    leaves a full traceback in the server log.
    """
    if is_unexpected(exc):
        logger.error("Unexpected %s while %s: %s", type(exc).__name__, what, exc, exc_info=exc)
    else:
        logger.debug("Skipped %s: %s", what, error_detail(exc))
