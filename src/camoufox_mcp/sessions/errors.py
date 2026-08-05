from __future__ import annotations

from playwright._impl._errors import TargetClosedError as _PlaywrightTargetClosedError
from playwright.async_api import Error as _PlaywrightError
from playwright.async_api import TimeoutError as _PlaywrightTimeoutError

# Re-exported so the tools layer can detect Playwright timeouts without importing
# playwright itself (tools -> sessions is the allowed dependency direction).
PLAYWRIGHT_TIMEOUT_ERROR: type[BaseException] = _PlaywrightTimeoutError
# Playwright's base class: every protocol/target/timeout error derives from it.
PLAYWRIGHT_ERROR: type[BaseException] = _PlaywrightError
# A closed tab or browser. Injected into the DOM layer, which distinguishes it from
# a destroyed execution context and must NEVER report it as a stale uid: telling an
# agent to re-snapshot a browser that is gone is an unbounded retry loop. It is not
# exported from playwright.async_api at this version, hence the private import.
PLAYWRIGHT_TARGET_CLOSED_ERROR: type[BaseException] = _PlaywrightTargetClosedError


class ProfileInUseError(RuntimeError):
    """A profile is already locked by another OS process."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        super().__init__(f"profile '{profile}' is locked by another process")


class NoActivePageError(RuntimeError):
    """The session holds no tab to act on: every one of them has been closed."""

    def __init__(self) -> None:
        super().__init__("No active page in this session")


class UnknownPageIndexError(ValueError):
    """A tab index that no longer names an open tab (or never did).

    A ``ValueError``: the index came from the caller, so it is a rejected argument
    rather than a defect, and the tool wrapper must not log a traceback for it.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        super().__init__(f"no page at index {index}")


class NoPendingDialogError(ValueError):
    """A dialog was answered when the tab had none waiting."""

    def __init__(self) -> None:
        super().__init__("No dialog is pending")


class UnknownDialogActionError(ValueError):
    """A dialog answer this layer has no branch for.

    The tool that takes the word from an agent rejects it first, against
    ``page.DIALOG_ACTIONS``, so reaching this is a defect in an internal caller
    rather than a typo: the message names the value, not the menu.
    """

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"unknown dialog action '{action}'")
