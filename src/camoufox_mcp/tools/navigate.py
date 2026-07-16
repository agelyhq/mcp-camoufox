from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.config import parse_headless, validate_fingerprint_os
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._observe import observe_suffix, validate_observe

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
        observe: str = "none",
        timeout: int = 30000,
    ) -> str:
        """Navigate a profile's active tab to a URL, lazily creating the session.

        On the first call for a profile a fresh Camoufox browser is launched with an
        anti-detect fingerprint. The optional session-creation parameters below are
        applied ONLY at that first launch; on later calls for an already-active
        profile they are ignored (the return value notes this). Each profile keeps a
        persistent on-disk state (cookies, storage) across launches.

        Tip — keep the viewport small for localhost dev loops: ``screenshot`` is
        billed by pixel count and is the single largest token sink, so a smaller
        window directly cuts image cost. Set ``viewport_width``/``viewport_height``
        (creation-only, e.g. 1000x700) or the server-wide ``CAMOUFOX_VIEWPORT`` env
        (e.g. "1000x700"); go larger only when a layout genuinely needs it.

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
            headless: Display mode — "true" (invisible, no display needed), "false"
                (a real visible window, needs a desktop GL stack) or "virtual"
                (invisible via a throwaway Xvfb X server on Linux). Creation-only;
                defaults to the server-wide CAMOUFOX_HEADLESS env (unset = visible).
                Caveat: "virtual" spawns Xvfb and repoints the PROCESS-GLOBAL DISPLAY
                to it, so a "virtual" session and a visible ("false") session in the
                same server process interfere — a visible session created after a
                virtual one inherits the 1x1 Xvfb display instead of the real desktop.
                Use a single display mode per server process; do not mix them.
            observe: Post-navigation observation appended to the result. "none"
                (default) appends nothing; "snapshot" appends a fresh snapshot
                (refreshes uids exactly like calling ``snapshot`` — earlier uids
                become stale); "text" appends the page body innerText (capped at 4000
                chars). Collapses navigate→snapshot / navigate→read into one call.
            timeout: Navigation timeout in milliseconds (default 30000).

        Returns:
            "Navigated to: <title> (<url>)". When creation options were supplied but
            the session already existed, an "(options ignored: ...)" note is appended;
            an observation block follows when ``observe`` is not "none".

        Errors:
            Returns "Error: ValueError: ..." for an invalid fingerprint_os, headless
            or observe value, "Error: ProfileInUseError: ..." if the profile is locked
            by another process, and "Timeout: ..." if the page does not load in time.
        """
        validate_observe(observe)
        init_opts = {
            "fingerprint_os": validate_fingerprint_os(fingerprint_os) if fingerprint_os else None,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "locale": locale,
            "block_images": block_images,
            "block_webrtc": block_webrtc,
            "headless": parse_headless(headless, unset=None),
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
        return result + await observe_suffix(page, observe)
