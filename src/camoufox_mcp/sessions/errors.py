from __future__ import annotations

from playwright.async_api import TimeoutError as _PlaywrightTimeoutError

# Re-exported so the tools layer can detect Playwright timeouts without importing
# playwright itself (tools -> sessions is the allowed dependency direction).
PLAYWRIGHT_TIMEOUT_ERROR: type[BaseException] = _PlaywrightTimeoutError


class ProfileInUseError(RuntimeError):
    """A profile is already locked by another OS process."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        super().__init__(f"profile '{profile}' is locked by another process")
