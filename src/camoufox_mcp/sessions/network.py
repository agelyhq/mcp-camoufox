from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from camoufox_mcp.sessions.log import PreservingLog

if TYPE_CHECKING:
    from playwright.async_api import Page, Request, Response

logger = logging.getLogger(__name__)


def format_status(status: int | None) -> str:
    """Render a captured request status: ``pending`` (no response), ``failed`` (errored), else the code."""
    if status is None:
        return "pending"
    if status == 0:
        return "failed"
    return str(status)


def read_post_data(request: Request) -> str | None:
    """Render a request body as text without ever raising out of the event listener.

    ``Request.post_data`` is a STRICT utf-8 decode of the raw body, so any binary
    payload (multipart upload, protobuf, gzip, a blob) raises ``UnicodeDecodeError``
    inside Playwright's event dispatch. Playwright catches that, stashes it on the
    connection and re-raises it on the NEXT api call, where ``rewrite_error`` does
    ``type(exc)(message)``, and ``UnicodeDecodeError`` needs 5 constructor
    arguments, so the caller gets the bare "TypeError: function takes exactly 5
    arguments (1 given)" of issue #13 on an unrelated tool. Read the raw buffer,
    which is a plain base64 decode and cannot fail that way.
    """
    raw = request.post_data_buffer
    if not raw:
        return None
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return f"<{len(raw)} bytes of binary data>"


@dataclass(eq=False)
class NetworkEntry:
    """Pure DTO describing one captured HTTP request; holds no live Playwright objects."""

    reqid: int
    method: str
    url: str
    resource_type: str
    request_headers: dict[str, str]
    post_data: str | None
    status: int | None = None
    response_headers: dict[str, str] | None = None


class NetworkMonitor:
    """The HTTP traffic of one tab, kept in a :class:`PreservingLog`."""

    def __init__(self) -> None:
        # Keyed by the Playwright Request object itself: identity is stable across the
        # request/response/requestfailed events, so the correct entry is always mutated.
        # Cleared with the live ring: an entry the tab's own navigation retired can no
        # longer be completed, and holding the key would leak the request object.
        self._pending: dict[Request, NetworkEntry] = {}
        # Response objects live here, not on the DTO. Weak keys drop the response as
        # soon as its entry is evicted from the rings and garbage-collected.
        self._responses: WeakKeyDictionary[NetworkEntry, Response] = WeakKeyDictionary()
        self._log: PreservingLog[NetworkEntry] = PreservingLog(on_rotate=self._pending.clear)
        # Maintained on insert so a caller watching for a navigation does not have to
        # copy and re-filter the whole ring on every poll tick. Never reset: ids only
        # grow, so the newest document request stays the highest across a rotation.
        self._last_document_reqid = -1

    def attach(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        self._log.attach(page)

    def _on_request(self, request: Request) -> None:
        entry = NetworkEntry(
            reqid=self._log.next_id(),
            method=request.method,
            url=request.url,
            resource_type=request.resource_type,
            request_headers=dict(request.headers),
            post_data=read_post_data(request),
        )
        self._log.record(entry)
        self._pending[request] = entry
        if entry.resource_type == "document":
            self._last_document_reqid = entry.reqid

    def _on_response(self, response: Response) -> None:
        entry = self._pending.pop(response.request, None)
        if entry is None:
            return
        entry.status = response.status
        entry.response_headers = dict(response.headers)
        self._responses[entry] = response

    def _on_request_failed(self, request: Request) -> None:
        entry = self._pending.pop(request, None)
        if entry is None:
            return
        entry.status = 0

    @property
    def last_document_reqid(self) -> int:
        """Id of the most recent document request, or -1 when the tab issued none.

        A document request is the earliest reliable evidence that a navigation has
        started, and this answers in O(1) so it can be polled every few milliseconds.
        """
        return self._last_document_reqid

    def list_entries(
        self,
        *,
        resource_types: list[str] | None = None,
        page_size: int | None = None,
        page_idx: int = 0,
        include_preserved: bool = False,
    ) -> tuple[list[NetworkEntry], int]:
        """Captured requests, oldest first, and the total that matched before paging."""
        wanted = {kind.lower() for kind in resource_types} if resource_types else None
        return self._log.select(
            keep=None if wanted is None else (lambda entry: entry.resource_type in wanted),
            page_size=page_size,
            page_idx=page_idx,
            include_preserved=include_preserved,
        )

    def get_entry(self, reqid: int) -> NetworkEntry | None:
        return self._log.find(lambda entry: entry.reqid == reqid)

    async def get_response_body(self, entry: NetworkEntry) -> str | None:
        """The response body the browser still holds, or None when it has none.

        Returned whole: capping and the truncation note are the tools layer's, which
        owns the one note the product emits and the parameter that raises it.
        """
        response = self._responses.get(entry)
        if response is None:
            return None
        try:
            return await response.text()
        except Exception:
            logger.debug("Failed to read response body for reqid=%d", entry.reqid, exc_info=True)
            return None
