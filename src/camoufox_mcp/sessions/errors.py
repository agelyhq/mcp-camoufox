from __future__ import annotations


class ProfileInUseError(RuntimeError):
    """A profile is already locked by another OS process."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        super().__init__(f"profile '{profile}' is locked by another process")
