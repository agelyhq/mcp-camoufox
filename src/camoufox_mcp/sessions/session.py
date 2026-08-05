from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions.addons import cleanup_addons, prepare_addons
from camoufox_mcp.sessions.launch import build_launch_kwargs
from camoufox_mcp.sessions.page import Page
from camoufox_mcp.sessions.page_book import PageBook
from camoufox_mcp.sessions.quiet import quiet_stdio
from camoufox_mcp.sessions.teardown import (
    CONTEXT_CLOSE_TIMEOUT,
    DRIVER_STOP_TIMEOUT,
    TAB_CLOSE_TIMEOUT,
    quietly,
)

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import BrowserContext, Playwright

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions
    from camoufox_mcp.sessions.page_book import PageInfo


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
        from camoufox.async_api import AsyncNewBrowser
        from playwright.async_api import async_playwright

        user_data_dir = config.ensure_profile_dir(profile)
        addon_dirs, addons_tmpdir = await prepare_addons(
            config.addon_urls, cache_dir=config.ensure_addons_dir()
        )

        # Everything the browser needs is now on disk, so every failure below has to
        # take the extracted addons and the driver with it.
        pw: Playwright | None = None
        try:
            kwargs = build_launch_kwargs(config, opts, user_data_dir, addon_dirs)
            pw = await async_playwright().start()
            # The one call that prints: on a first launch camoufox fetches the browser
            # build and the GeoIP database and reports progress on stdout. The silence
            # covers it alone, because it swaps the process streams: everything else
            # here logs to a file, and anything running concurrently would have had its
            # own output swallowed too.
            with quiet_stdio():
                context = await AsyncNewBrowser(pw, **kwargs)
        except Exception:
            if pw is not None:
                await quietly("Playwright stop", pw.stop(), DRIVER_STOP_TIMEOUT)
            cleanup_addons(addons_tmpdir)
            raise

        session = cls(profile=profile, playwright=pw, context=context, addons_tmpdir=addons_tmpdir)
        try:
            await session._open_initial_page()
        except Exception:
            # The browser is already running at this point, and only this object knows
            # how to stop it. Left to the caller, which holds nothing but the profile
            # filelock, the Camoufox process would outlive the failure and keep the
            # profile directory for itself.
            await session.close()
            raise
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
            await page.goto(url)
        return index

    async def close_page(self, index: int) -> None:
        page = self._pages.remove(index)
        await page.close()

    def select_page(self, index: int) -> None:
        self._pages.select(index)

    async def close(self) -> None:
        """Stop the browser and the driver behind it. Bounded, and never raises."""
        for page in self._pages.all_pages():
            await quietly("Page close", page.close(), TAB_CLOSE_TIMEOUT)
        await quietly("Context close", self._context.close(), CONTEXT_CLOSE_TIMEOUT)
        await quietly("Playwright stop", self._pw.stop(), DRIVER_STOP_TIMEOUT)
        cleanup_addons(self._addons_tmpdir)

    async def _open_initial_page(self) -> None:
        """Adopt the context's pages (or open one). Never sets a viewport size.

        The requested size already reached Camoufox as ``window=(w, h)``, which pins
        the real window AND the spoofed ``window.outer*``. Forcing the viewport on top
        of that overrides ``innerHeight`` to the outer height, so the page reports a
        window with zero browser chrome (measured: 900x700 outer, 900x700 inner
        instead of 900x649), an impossible geometry, and exactly the kind of tell
        Camoufox 0.5's ``clamp_window_dimensions``/``fix_screen_no_taskbar`` remove.
        It also re-enters the unbounded Juggler resize handshake that
        ``no_viewport`` exists to avoid (daijro/camoufox#666).
        """
        existing = self._context.pages
        if existing:
            for pw_page in existing:
                self._pages.add(Page(pw_page))
        else:
            await self.new_page()
