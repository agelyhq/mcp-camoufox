from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox_mcp.session_defaults import SessionDefaults


@dataclass(frozen=True)
class SessionInitOptions:
    """Resolved per-session creation options (server defaults merged with per-call overrides).

    Applied only when a session is first created; ignored for an already-active profile.
    ``headless`` is the sole option whose server-wide default lives outside
    :class:`SessionDefaults` (it is the top-level ``config.headless``): ``None`` here
    means "fall back to that config value", resolved at launch time.
    """

    fingerprint_os: str | None
    viewport_width: int | None
    viewport_height: int | None
    locale: str | None
    block_images: bool
    block_webrtc: bool
    headless: bool | str | None

    @classmethod
    def resolve(
        cls,
        defaults: SessionDefaults,
        *,
        fingerprint_os: str | None = None,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        locale: str | None = None,
        block_images: bool | None = None,
        block_webrtc: bool | None = None,
        headless: bool | str | None = None,
    ) -> SessionInitOptions:
        return cls(
            fingerprint_os=fingerprint_os or defaults.fingerprint_os,
            viewport_width=viewport_width or defaults.viewport_width,
            viewport_height=viewport_height or defaults.viewport_height,
            locale=locale or defaults.locale,
            block_images=defaults.block_images if block_images is None else block_images,
            block_webrtc=defaults.block_webrtc if block_webrtc is None else block_webrtc,
            headless=headless,
        )
