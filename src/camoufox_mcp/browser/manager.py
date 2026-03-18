from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from camoufox_mcp.browser.addons import cleanup_addons, prepare_addons
from camoufox_mcp.browser.page_handle import PageHandle

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Playwright

    from camoufox_mcp.browser.config import ServerConfig, SessionParams

logger = logging.getLogger(__name__)


@dataclass
class PageInfo:
    handle: PageHandle
    index: int


class BrowserManager:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._pw: Playwright | None = None
        self._browser: BrowserContext | None = None
        self._addons_tmpdir: Path | None = None
        self._session_tmpdir: tempfile.TemporaryDirectory | None = None  # type: ignore[type-arg]
        self.pages: dict[int, PageInfo] = {}
        self._next_page_idx: int = 0
        self.active_page_idx: int = -1
        self._active_profile: str | None = None

    @property
    def is_running(self) -> bool:
        return self._browser is not None

    async def start_session(self, params: SessionParams) -> None:
        if self.is_running:
            raise RuntimeError("A session is already running. Close it before starting a new one.")

        from camoufox.async_api import AsyncNewBrowser
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()

        addon_dirs, self._addons_tmpdir = await prepare_addons(self.config.addon_urls)

        self._session_tmpdir = tempfile.TemporaryDirectory(prefix="camoufox-mcp-")
        profile_dir = await self._prepare_profile(params.profile, Path(self._session_tmpdir.name))
        self._active_profile = params.profile

        kwargs: dict[str, Any] = {
            "headless": self.config.headless,
            "os": params.target_os,
            "geoip": True,
            "humanize": True,
            "block_images": params.block_images,
            "block_webrtc": params.block_webrtc,
            "persistent_context": True,
            "user_data_dir": str(profile_dir),
        }
        if addon_dirs:
            kwargs["addons"] = addon_dirs
        if self.config.proxy:
            kwargs["proxy"] = {"server": self.config.proxy}
        if self.config.camoufox_binary:
            kwargs["executable_path"] = self.config.camoufox_binary

        self._browser = await AsyncNewBrowser(self._pw, **kwargs)
        idx = await self._create_page()
        page = self.pages[idx].handle
        await page.set_viewport(params.viewport_width, params.viewport_height)

    async def stop_session(self) -> None:
        if not self.is_running:
            return

        for page_info in list(self.pages.values()):
            try:
                await page_info.handle.close()
            except Exception:
                logger.debug("Page close failed during shutdown", exc_info=True)
        self.pages.clear()
        self._next_page_idx = 0
        self.active_page_idx = -1

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                logger.debug("Browser close failed", exc_info=True)
            self._browser = None

        if self._pw:
            await self._pw.stop()
            self._pw = None

        cleanup_addons(self._addons_tmpdir)
        self._addons_tmpdir = None

        if self._active_profile and self._session_tmpdir:
            await self._finalize_profile(self._active_profile, Path(self._session_tmpdir.name))
            self._active_profile = None

        if self._session_tmpdir:
            self._session_tmpdir.cleanup()
            self._session_tmpdir = None

    async def new_page(self) -> int:
        self._require_running()
        return await self._create_page()

    async def close_page(self, idx: int) -> None:
        page_info = self.pages.pop(idx, None)
        if not page_info:
            raise ValueError(f"No page at index {idx}")
        await page_info.handle.close()
        if self.active_page_idx == idx:
            self.active_page_idx = next(iter(self.pages), -1)

    @property
    def active_page(self) -> PageHandle:
        if self.active_page_idx not in self.pages:
            raise RuntimeError("No active page. Start a session first.")
        return self.pages[self.active_page_idx].handle

    def _require_running(self) -> None:
        if not self.is_running:
            raise RuntimeError("No active session. Call start_session first.")

    async def _create_page(self) -> int:
        if self._browser is None:
            raise RuntimeError("Browser not started")
        pw_page = await self._browser.new_page()
        handle = PageHandle(pw_page)
        idx = self._next_page_idx
        self._next_page_idx += 1
        self.pages[idx] = PageInfo(handle=handle, index=idx)
        self.active_page_idx = idx
        return idx

    async def _prepare_profile(self, name: str, tmpdir: Path) -> Path:
        """Pull profile from S3 into tmpdir. S3 must be configured."""
        if not self.config.s3:
            msg = "S3 is not configured. Set CAMOUFOX_S3_ENDPOINT, CAMOUFOX_S3_ACCESS_KEY, CAMOUFOX_S3_SECRET_KEY, CAMOUFOX_S3_BUCKET to use profiles."
            raise RuntimeError(msg)
        from camoufox_mcp.browser.profile_store import pull_profile

        return await pull_profile(self.config.s3, name, tmpdir)

    async def _finalize_profile(self, name: str, tmpdir: Path) -> None:
        """Push profile from tmpdir to S3."""
        if not self.config.s3:
            return
        from camoufox_mcp.browser.profile_store import push_profile

        await push_profile(self.config.s3, name, tmpdir)
