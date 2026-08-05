from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.config import parse_headless, validate_fingerprint_os
from camoufox_mcp.sessions import SessionInitOptions
from camoufox_mcp.tools._base import DEFAULT_TIMEOUT_MS, get_page, get_session, tool
from camoufox_mcp.tools._observe import ObserveMode, validate_observe

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
        headless: str | None = None,
        observe: ObserveMode = "none",
        timeout: int = DEFAULT_TIMEOUT_MS,
    ) -> str:
        """Navigate the profile's active tab to a URL, creating the session on first use.

        The options below shape the browser at that first launch only. On a later call
        for an active profile they are ignored and the result says which ones were.

        Args:
            url: Absolute URL, scheme included.
            fingerprint_os: Spoofed OS: windows, macos or linux.
            viewport_width: Pixels.
            viewport_height: Pixels.
            locale: e.g. "en-US".
            headless: "true" (invisible), "false" (a real window, needs a desktop GL
                stack) or "virtual" (invisible via Xvfb, Linux only).
            timeout: Navigation timeout in milliseconds.
        """
        validate_observe(observe)
        # Resolved into the frozen options object here, at the only boundary that
        # takes these words from an agent, so a renamed option is a signature error
        # rather than a keyword nobody reads 3 calls down.
        opts = SessionInitOptions.resolve(
            deps.config.session_defaults,
            fingerprint_os=validate_fingerprint_os(fingerprint_os) if fingerprint_os else None,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            locale=locale,
            block_images=block_images,
            block_webrtc=block_webrtc,
            headless=parse_headless(headless, unset=None),
        )
        supplied = _supplied_names(
            fingerprint_os=fingerprint_os,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            locale=locale,
            block_images=block_images,
            block_webrtc=block_webrtc,
            headless=headless,
        )

        already_active = deps.sessions.get(profile) is not None
        session = await get_session(deps, profile, opts)
        page = get_page(session)
        await page.goto(url, timeout=timeout)

        result = f"Navigated to: {await page.title()} ({page.url})"
        if supplied and already_active:
            result += f" (options ignored: {', '.join(supplied)}; session already active)"
        return result

    def _supplied_names(**options: object) -> list[str]:
        """The creation options this call actually named, for the "ignored" note."""
        return sorted(name for name, value in options.items() if value is not None)
