from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from camoufox_mcp.sessions.errors import NoActivePageError, UnknownPageIndexError

if TYPE_CHECKING:
    from camoufox_mcp.sessions.page import Page


@dataclass(frozen=True)
class PageInfo:
    """Public view of a single tab for listing purposes."""

    index: int
    page: Page
    is_active: bool


class PageBook:
    """Multi-tab bookkeeping for one session: stable integer indices + active tab.

    ``None`` is the absence of an active tab, and it is a state the book reaches on
    its own: closing the last tab leaves the session with nothing to act on.
    """

    def __init__(self) -> None:
        self._pages: dict[int, Page] = {}
        self._next_index: int = 0
        self._active_index: int | None = None

    @property
    def count(self) -> int:
        return len(self._pages)

    @property
    def active(self) -> Page:
        page = None if self._active_index is None else self._pages.get(self._active_index)
        if page is None:
            raise NoActivePageError
        return page

    def add(self, page: Page) -> int:
        index = self._next_index
        self._next_index += 1
        self._pages[index] = page
        self._active_index = index
        return index

    def remove(self, index: int) -> Page:
        self._require(index)
        page = self._pages.pop(index)
        if self._active_index == index:
            self._active_index = next(iter(self._pages), None)
        return page

    def select(self, index: int) -> None:
        self._require(index)
        self._active_index = index

    def items(self) -> list[PageInfo]:
        return [
            PageInfo(index=i, page=p, is_active=(i == self._active_index))
            for i, p in sorted(self._pages.items())
        ]

    def all_pages(self) -> list[Page]:
        return list(self._pages.values())

    def _require(self, index: int) -> None:
        if index not in self._pages:
            raise UnknownPageIndexError(index)
