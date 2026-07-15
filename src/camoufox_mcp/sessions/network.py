from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from playwright.async_api import Page, Request, Response

logger = logging.getLogger(__name__)

MAX_ENTRIES = 1000


def format_status(status: int | None) -> str:
    """Render a captured request status: ``pending`` (no response), ``failed`` (errored), else the code."""
    if status is None:
        return "pending"
    if status == 0:
        return "failed"
    return str(status)


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
    timestamp: float = field(default_factory=time.time)


class NetworkMonitor:
    def __init__(self) -> None:
        self._entries: deque[NetworkEntry] = deque(maxlen=MAX_ENTRIES)
        self._preserved: deque[NetworkEntry] = deque(maxlen=MAX_ENTRIES)
        self._next_reqid: int = 0
        # Keyed by the Playwright Request object itself: identity is stable across the
        # request/response/requestfailed events, so the correct entry is always mutated.
        self._pending: dict[Request, NetworkEntry] = {}
        # Response objects live here, not on the DTO. Weak keys drop the response as
        # soon as its entry is evicted from the deques and garbage-collected.
        self._responses: WeakKeyDictionary[NetworkEntry, Response] = WeakKeyDictionary()

    def attach(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        page.on("framenavigated", self._on_navigation)

    def _on_navigation(self, _: Any) -> None:
        self._preserved.extend(self._entries)
        while len(self._preserved) > MAX_ENTRIES:
            self._preserved.popleft()
        self._entries.clear()
        self._pending.clear()

    def _on_request(self, request: Request) -> None:
        reqid = self._next_reqid
        self._next_reqid += 1

        entry = NetworkEntry(
            reqid=reqid,
            method=request.method,
            url=request.url,
            resource_type=request.resource_type,
            request_headers=dict(request.headers),
            post_data=request.post_data,
        )
        self._entries.append(entry)
        self._pending[request] = entry

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

    def list_entries(
        self,
        *,
        resource_types: list[str] | None = None,
        page_size: int | None = None,
        page_idx: int = 0,
        include_preserved: bool = False,
    ) -> tuple[list[NetworkEntry], int]:
        source: list[NetworkEntry] = list(self._entries)
        if include_preserved:
            source = list(self._preserved) + source

        if resource_types:
            types_set = {rt.lower() for rt in resource_types}
            source = [e for e in source if e.resource_type in types_set]

        total = len(source)

        if page_size is not None:
            start = page_idx * page_size
            source = source[start : start + page_size]

        return source, total

    def get_entry(self, reqid: int) -> NetworkEntry | None:
        for entry in self._entries:
            if entry.reqid == reqid:
                return entry
        for entry in self._preserved:
            if entry.reqid == reqid:
                return entry
        return None

    async def get_response_body(self, entry: NetworkEntry, max_size: int = 50000) -> str | None:
        response = self._responses.get(entry)
        if response is None:
            return None
        try:
            body = await response.text()
        except Exception:
            logger.debug("Failed to read response body for reqid=%d", entry.reqid, exc_info=True)
            return None
        if len(body) > max_size:
            return body[:max_size] + f"\n... [truncated, {len(body)} total chars]"
        return body
