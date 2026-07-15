from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionDefaults:
    """Per-session defaults applied at session creation, overridable per navigate call."""

    fingerprint_os: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    locale: str | None = None
    block_images: bool = False
    block_webrtc: bool = False
