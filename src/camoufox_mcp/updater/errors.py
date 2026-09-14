from __future__ import annotations


class BrowserSetupError(RuntimeError):
    """Raised when no usable Camoufox binary is available and it cannot be fetched."""


class FetchError(RuntimeError):
    """A fetch child exited non-zero; the message carries its exit status and stderr tail."""

    def __init__(self, asset: str, returncode: int, stderr_tail: str) -> None:
        self.asset = asset
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        detail = stderr_tail or "no output on stderr"
        super().__init__(f"{asset} fetch exited with status {returncode}: {detail}")
