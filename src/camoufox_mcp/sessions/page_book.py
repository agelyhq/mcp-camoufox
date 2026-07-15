from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.sessions.pages import PageInfo

if TYPE_CHECKING:
    from camoufox_mcp.sessions.page import Page


class PageBook:
    """Multi-tab bookkeeping for one session: stable integer indices + active tab."""

    def __init__(self) -> None:
        self._pages: dict[int, Page] = {}
        self._next_index: int = 0
        self._active_index: int = -1

    @property
    def count(self) -> int:
        return len(self._pages)

    @property
    def active(self) -> Page:
        page = self._pages.get(self._active_index)
        if page is None:
            raise RuntimeError("No active page in this session")
        return page

    def add(self, page: Page) -> int:
        index = self._next_index
        self._next_index += 1
        self._pages[index] = page
        self._active_index = index
        return index

    def remove(self, index: int) -> Page:
        if index not in self._pages:
            raise ValueError(f"no page at index {index}")
        page = self._pages.pop(index)
        if self._active_index == index:
            self._active_index = next(iter(self._pages), -1)
        return page

    def select(self, index: int) -> None:
        if index not in self._pages:
            raise ValueError(f"no page at index {index}")
        self._active_index = index

    def items(self) -> list[PageInfo]:
        return [
            PageInfo(index=i, page=p, is_active=(i == self._active_index))
            for i, p in sorted(self._pages.items())
        ]

    def all_pages(self) -> list[Page]:
        return list(self._pages.values())
