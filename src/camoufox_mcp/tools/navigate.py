from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.config import VALID_OS
from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def navigate(
        profile: str,
        url: str,
        fingerprint_os: str | None = None,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        locale: str | None = None,
        block_images: bool | None = None,
        block_webrtc: bool | None = None,
        timeout: int = 30000,
    ) -> str:
        """Navigate a profile's active tab to a URL, lazily creating the session.

        On the first call for a profile a fresh Camoufox browser is launched with an
        anti-detect fingerprint. The optional session-creation parameters below are
        applied ONLY at that first launch; on later calls for an already-active
        profile they are ignored (the return value notes this). Each profile keeps a
        persistent on-disk state (cookies, storage) across launches.

        Args:
            profile: Session identifier. Reused across calls; created on demand.
            url: Absolute URL to load (include the scheme, e.g. https://).
            fingerprint_os: Spoofed OS for the fingerprint — one of windows, macos,
                linux. Creation-only. Defaults to the server's configured value.
            viewport_width: Viewport width in pixels. Creation-only.
            viewport_height: Viewport height in pixels. Creation-only.
            locale: Browser locale (e.g. "en-US", "fr-FR"). Creation-only.
            block_images: If true, image loading is blocked. Creation-only.
            block_webrtc: If true, WebRTC is blocked. Creation-only.
            timeout: Navigation timeout in milliseconds (default 30000).

        Returns:
            "Navigated to: <title> (<url>)". When creation options were supplied but
            the session already existed, an "(options ignored: ...)" note is appended.

        Errors:
            Returns "Error: ValueError: ..." for an invalid fingerprint_os,
            "Error: ProfileInUseError: ..." if the profile is locked by another
            process, and "Timeout: ..." if the page does not finish loading in time.
        """
        if fingerprint_os is not None and fingerprint_os.lower() not in VALID_OS:
            raise ValueError(
                f"invalid fingerprint_os '{fingerprint_os}'; "
                f"must be one of {', '.join(sorted(VALID_OS))}"
            )

        init_opts = {
            "fingerprint_os": fingerprint_os.lower() if fingerprint_os else None,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "locale": locale,
            "block_images": block_images,
            "block_webrtc": block_webrtc,
        }
        supplied = {k: v for k, v in init_opts.items() if v is not None}

        already_active = deps.sessions.get(profile) is not None
        session = await get_session(deps, profile, **supplied)
        page = get_page(session)
        await page.raw.goto(url, timeout=timeout, wait_until="load")
        page.record_navigation(page.url)

        result = f"Navigated to: {await page.title()} ({page.url})"
        if supplied and already_active:
            result += f" (options ignored: {', '.join(sorted(supplied))}; session already active)"
        return result
