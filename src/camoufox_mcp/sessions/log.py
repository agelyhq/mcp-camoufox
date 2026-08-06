from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from camoufox_mcp.sessions.errors import PLAYWRIGHT_ERROR

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.async_api import Frame, Page, Request

# Entries held per ring, per tab. Both rings are bounded deques, so the oldest entry
# is evicted on insertion and no caller ever has to trim them.
MAX_ENTRIES = 1000


def _is_main_frame(frame: Frame) -> bool:
    """Whether ``frame`` is the frame carrying its own tab's document.

    Identity, never URL: an embed showing the same address as its parent is still an
    embed. The single place the comparison is written, because both event sources feeding
    a monitor have to make it.
    """
    return frame is frame.page.main_frame


def is_main_frame_request(request: Request) -> bool:
    """Whether THIS TAB's main frame is what asked for ``request``.

    The distinction :func:`on_main_frame_navigation` makes, on the other event source.
    Firefox reports an embed's own document under the same ``document`` resource type as
    the tab's, so resource type alone cannot tell a navigation of the tab from an ad slot
    loading in the middle of the current document's life. Measured on the 152.0.4-beta.28
    build: the tab's document request answers with the main frame, a declared iframe's and
    a freshly injected iframe's both answer with a sub-frame.

    Reading the frame off a request can raise instead of answering, and every case it
    raises for is a no anyway, so the error is the answer: a service worker's request has
    no frame at all, and Playwright reports a navigation request whose frame does not
    exist yet the same way. The main frame is never either of those, since it exists for
    as long as the tab does. Raising out of here would land in Playwright's event
    dispatch, which stashes the exception and re-raises it on the next unrelated api call.
    """
    try:
        return _is_main_frame(request.frame)
    except PLAYWRIGHT_ERROR:
        return False


def on_main_frame_navigation(page: Page, handler: Callable[[], object]) -> None:
    """Call ``handler`` when THIS TAB's own document is replaced, and only then.

    ``framenavigated`` fires for every frame in the tab, and a page carrying an ad, a
    captcha or any embed navigates sub-frames of its own long after it has finished
    loading. Treating one of those as a navigation moved the document's own entries into
    the preserved ring and emptied the live one, so the default listing answered "No
    network requests captured." on a page that had just loaded, and every in-flight
    request stayed "pending" forever. Only the main frame carries the tab's document;
    ``page.py``'s ``_on_loaded`` states the same reasoning for the element store.
    """

    def dispatch(frame: Frame) -> None:
        if _is_main_frame(frame):
            handler()

    page.on("framenavigated", dispatch)


class PreservingLog[T]:
    """A tab's bounded observation ring, rotated when its document is replaced.

    Both per-tab monitors are this object plus a decoder: a live ring holding the
    current document's entries, a second ring holding what the previous document
    left behind, and one monotonic id per entry so a listing can be turned back
    into a lookup. ``include_preserved`` is what reaches across the rotation.

    Reading is one contract for both monitors: :meth:`select` filters, paginates
    and reports the pre-pagination total, so a caller can always say how much it
    did not show.

    Rotating is the monitor's decision, not this class's: whoever owns the entries is
    the only one that can tell which of them the replaced document left behind. See
    :meth:`rotate`.
    """

    def __init__(self) -> None:
        self._entries: deque[T] = deque(maxlen=MAX_ENTRIES)
        self._preserved: deque[T] = deque(maxlen=MAX_ENTRIES)
        self._next_id = 0

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

    def rotate(self, retire: Callable[[T], bool] | None = None) -> list[T]:
        """Move the retired entries to the preserved ring; return them, in order.

        ``retire`` names the entries the replaced document left behind. ``None`` means
        the whole live ring, which is the only answer available to a monitor whose
        entries carry no evidence of which document they belong to.

        Everything ``retire`` rejects STAYS LIVE. That is the point of the predicate:
        the events feeding a ring and the event announcing the navigation do not share
        a source, so entries belonging to the new document can already be in the ring
        when this runs, and a wholesale rotation loses them.
        """
        kept: deque[T] = deque(maxlen=MAX_ENTRIES)
        retired: list[T] = []
        for entry in self._entries:
            if retire is None or retire(entry):
                retired.append(entry)
            else:
                kept.append(entry)
        self._preserved.extend(retired)
        self._entries = kept
        return retired

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
