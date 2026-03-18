from __future__ import annotations

from fastmcp import Context, FastMCP  # noqa: TC002

from camoufox_mcp.browser.config import VALID_OS, SessionParams
from camoufox_mcp.tools._context import get_manager


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def navigate(
        url: str,
        profile: str,
        ctx: Context,
        timeout: int = 30000,
        target_os: str = "windows",
        viewport_width: int = 1280,
        viewport_height: int = 800,
        block_images: bool = False,
        block_webrtc: bool = False,
    ) -> str:
        """Navigate the active page to a URL. Starts a browser session automatically if needed.

        Session parameters are only used when starting a new session. If a session
        is already running, they are ignored.

        Args:
            url: Absolute URL to navigate to
            profile: Profile name for persistent context (cookies/storage survive restarts).
                     Resolved under CAMOUFOX_PROFILES_DIR. Downloaded from S3 if configured.
            timeout: Max wait time in ms (default 30000)
            target_os: Fingerprint target OS — windows, linux, or macos (default: windows)
            viewport_width: Browser viewport width in pixels (default: 1280)
            viewport_height: Browser viewport height in pixels (default: 800)
            block_images: Block image loading for faster browsing (default: false)
            block_webrtc: Block WebRTC to prevent IP leaks (default: false)
        """
        try:
            manager = get_manager(ctx)

            if not manager.is_running:
                if target_os not in VALID_OS:
                    return f"Error: Invalid target_os={target_os!r}. Must be one of: {', '.join(sorted(VALID_OS))}"
                params = SessionParams(
                    profile=profile,
                    target_os=target_os,
                    viewport_width=viewport_width,
                    viewport_height=viewport_height,
                    block_images=block_images,
                    block_webrtc=block_webrtc,
                )
                await manager.start_session(params)

            page = manager.active_page
            result = await page.navigate(url, timeout=timeout / 1000)
            return f"Navigated to: {result['title']} ({result['url']})"
        except TimeoutError as e:
            return f"Timeout: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
