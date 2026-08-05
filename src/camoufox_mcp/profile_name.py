from __future__ import annotations

import re
from typing import TypeGuard

# A profile name is not a label: it becomes 3 real filesystem paths, the persistent
# profile directory `<profiles>/<name>`, its sibling lock `<profiles>/<name>.lock`,
# and the telemetry log `<logs>/<name>.jsonl`. Unvalidated, `../../x` and `/tmp/x`
# both resolve outside the data root (measured: a telemetry line was written 2
# directories above `logs/`), `..` resolves to the data root itself, and an empty
# name collides with the `_server` bucket. The token is therefore deliberately
# narrower than what the filesystem itself accepts.
MAX_PROFILE_LEN = 64
ALLOWED_PROFILE_CHARS = "letters, digits, '.', '_' and '-'"

# The leading character must be alphanumeric, which is what rejects `.`, `..`,
# dotfiles, and any name starting with `_` (the reserved telemetry bucket prefix).
_PROFILE_RE = re.compile(rf"[A-Za-z0-9][A-Za-z0-9._-]{{0,{MAX_PROFILE_LEN - 1}}}")

# How much of a rejected name is echoed back. Small enough that the whole message
# stays under the 200-char telemetry note cap, so the error is never logged
# truncated, and so a megabyte-long name cannot produce a megabyte-long line.
_ECHO_LIMIT = 32


class InvalidProfileNameError(ValueError):
    """A profile name that is not a filename-safe token.

    Rendered by the tool wrapper as a single line naming what is allowed. The
    offending name is echoed through ``repr`` so invisible characters (the real
    case was a name ending in ``">\\n``) are visible and cannot break the line.
    """

    def __init__(self, profile: object) -> None:
        text = profile if isinstance(profile, str) else repr(profile)
        shown = text[:_ECHO_LIMIT]
        elision = "..." if len(text) > _ECHO_LIMIT else ""
        super().__init__(
            f"profile {shown!r}{elision} is not a valid name; use 1 to {MAX_PROFILE_LEN} "
            f"characters from {ALLOWED_PROFILE_CHARS}, starting with a letter or digit"
        )
        self.profile = profile


def is_valid_profile(profile: object) -> TypeGuard[str]:
    """Whether ``profile`` is a filename-safe token. Never raises, never rewrites."""
    return isinstance(profile, str) and _PROFILE_RE.fullmatch(profile) is not None


def validate_profile(profile: str) -> str:
    """Return ``profile`` unchanged, or raise :class:`InvalidProfileNameError`.

    Deliberately never sanitises: an agent that asked for profile X and silently got
    profile Y would keep driving the wrong browser state.
    """
    if not is_valid_profile(profile):
        raise InvalidProfileNameError(profile)
    return profile
