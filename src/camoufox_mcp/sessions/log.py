from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.async_api import Frame, Page

# Entries held per ring, per tab. Both rings are bounded deques, so the oldest entry
# is evicted on insertion and no caller ever has to trim them.
MAX_ENTRIES = 1000


class PreservingLog[T]:
    """A tab's bounded observation ring, rotated when its document is replaced.

    Both per-tab monitors are this object plus a decoder: a live ring holding the
    current document's entries, a second ring holding what the previous document
    left behind, and one monotonic id per entry so a listing can be turned back
    into a lookup. ``include_preserved`` is what reaches across the rotation.

    Reading is one contract for both monitors: :meth:`select` filters, paginates
    and reports the pre-pagination total, so a caller can always say how much it
    did not show.
    """

    def __init__(self, on_rotate: Callable[[], None] | None = None) -> None:
        self._entries: deque[T] = deque(maxlen=MAX_ENTRIES)
        self._preserved: deque[T] = deque(maxlen=MAX_ENTRIES)
        self._next_id = 0
        self._on_rotate = on_rotate

    def attach(self, page: Page) -> None:
        """Subscribe to the tab's navigations so the rings rotate with its document."""
        page.on("framenavigated", self._on_navigation)

    def next_id(self) -> int:
        """The id of the next entry: unique per tab, monotonic across rotations."""
        entry_id = self._next_id
        self._next_id += 1
        return entry_id

    def record(self, entry: T) -> None:
        self._entries.append(entry)

    def find(self, match: Callable[[T], bool]) -> T | None:
        """The first entry satisfying ``match``, current document first."""
        for entry in (*self._entries, *self._preserved):
            if match(entry):
                return entry
        return None

    def select(
        self,
        *,
        keep: Callable[[T], bool] | None = None,
        page_size: int | None = None,
        page_idx: int = 0,
        include_preserved: bool = False,
    ) -> tuple[list[T], int]:
        """Filter, then page. Returns the page and the total that matched before it."""
        source = list(self._entries)
        if include_preserved:
            source = list(self._preserved) + source
        if keep is not None:
            source = [entry for entry in source if keep(entry)]

        total = len(source)
        if page_size is not None:
            start = page_idx * page_size
            source = source[start : start + page_size]
        return source, total

    def _on_navigation(self, frame: Frame) -> None:
        """Rotate the rings, but only when THIS TAB's own document is replaced.

        ``framenavigated`` fires for every frame in the tab, and a page carrying an
        ad, a captcha or any embed navigates sub-frames of its own long after it has
        finished loading. Treating one of those as a navigation moved the document's
        own entries into the preserved ring and emptied the live one, so the default
        listing answered "No network requests captured." on a page that had just
        loaded, and every in-flight request stayed "pending" forever. Only the main
        frame carries the tab's document; ``page.py``'s ``_on_loaded`` states the same
        reasoning for the element store.
        """
        if frame is not frame.page.main_frame:
            return
        self._preserved.extend(self._entries)
        self._entries.clear()
        if self._on_rotate is not None:
            self._on_rotate()
