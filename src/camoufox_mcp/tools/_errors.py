from __future__ import annotations

from camoufox_mcp.sessions.errors import PLAYWRIGHT_TIMEOUT_ERROR

# Playwright's base exception class is literally named ``Error`` (``__name__ ==
# "Error"``), which would render as the meaningless "Error: Error: ...". Map the
# bare name to something legible while keeping the real type for every other class.
_BARE_ERROR_ALIAS = "PlaywrightError"

# Everything from this marker onward is Playwright's multi-line action trace; it can
# be thousands of chars and is noise to the model, so it is dropped entirely.
_CALL_LOG_MARKER = "Call log:"


def error_type_name(exc: BaseException) -> str:
    """The exception's class name, aliasing Playwright's bare ``Error``."""
    name = type(exc).__name__
    return _BARE_ERROR_ALIAS if name == "Error" else name


def collapse_message(message: str) -> str:
    """Cut the Playwright call log and fold newlines so the message is one line."""
    head = message.split(_CALL_LOG_MARKER, 1)[0]
    return "; ".join(part.strip() for part in head.splitlines() if part.strip())


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
