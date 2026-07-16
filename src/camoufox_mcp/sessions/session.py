from __future__ import annotations

import contextlib
import io
import logging
from typing import TYPE_CHECKING

from camoufox_mcp.sessions.addons import cleanup_addons, prepare_addons
from camoufox_mcp.sessions.launch import build_launch_kwargs
from camoufox_mcp.sessions.page import Page
from camoufox_mcp.sessions.page_book import PageBook

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import BrowserContext, Playwright

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions
    from camoufox_mcp.sessions.pages import PageInfo

logger = logging.getLogger(__name__)


class Session:
    """One live Camoufox browser bound to a persistent profile.

    Owns the Playwright ``BrowserContext``, its multi-tab bookkeeping and the
    per-tab network/console monitors. The cross-process filelock lifecycle is
    owned by :class:`SessionManager`, not by this object.
    """

    def __init__(
        self,
        *,
        profile: str,
        playwright: Playwright,
        context: BrowserContext,
        addons_tmpdir: Path | None,
    ) -> None:
        self.profile = profile
        self._pw = playwright
        self._context = context
        self._addons_tmpdir = addons_tmpdir
        self._pages = PageBook()

    @classmethod
    async def create(
        cls,
        *,
        config: ServerConfig,
        profile: str,
        opts: SessionInitOptions,
    ) -> Session:
        from playwright.async_api import async_playwright

        user_data_dir = config.ensure_profile_dir(profile)

        # On first launch camoufox downloads addons/GeoIP and prints progress to
        # stdout; silence it so the stdio MCP protocol framing is never corrupted.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            addon_dirs, addons_tmpdir = await prepare_addons(config.addon_urls)
            kwargs = build_launch_kwargs(config, opts, user_data_dir, addon_dirs)

            pw = await async_playwright().start()
            try:
                from camoufox.async_api import AsyncNewBrowser

                context = await AsyncNewBrowser(pw, **kwargs)
            except Exception:
                await pw.stop()
                cleanup_addons(addons_tmpdir)
                raise

        session = cls(profile=profile, playwright=pw, context=context, addons_tmpdir=addons_tmpdir)
        await session._open_initial_page(opts)
        return session

    @property
    def active_page(self) -> Page:
        return self._pages.active

    @property
    def page_count(self) -> int:
        return self._pages.count

    def list_pages(self) -> list[PageInfo]:
        return self._pages.items()

    async def new_page(self, url: str | None = None) -> int:
        pw_page = await self._context.new_page()
        page = Page(pw_page)
        index = self._pages.add(page)
        if url:
            await pw_page.goto(url, wait_until="load")
            page.record_navigation(page.url)
        return index

    async def close_page(self, index: int) -> None:
        page = self._pages.remove(index)
        await page.close()

    def select_page(self, index: int) -> None:
        self._pages.select(index)

    async def close(self) -> None:
        for page in self._pages.all_pages():
            try:
                await page.close()
            except Exception:
                logger.debug("Page close failed during session shutdown", exc_info=True)
        try:
            await self._context.close()
        except Exception:
            logger.debug("Context close failed", exc_info=True)
        try:
            await self._pw.stop()
        except Exception:
            logger.debug("Playwright stop failed", exc_info=True)
        cleanup_addons(self._addons_tmpdir)

    async def _open_initial_page(self, opts: SessionInitOptions) -> None:
        existing = self._context.pages
        if existing:
            for pw_page in existing:
                self._pages.add(Page(pw_page))
        else:
            await self.new_page()
        if opts.viewport_width and opts.viewport_height:
            await self._pages.active.raw.set_viewport_size(
                {"width": opts.viewport_width, "height": opts.viewport_height}
            )
