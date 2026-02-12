from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page, Request, Response

logger = logging.getLogger(__name__)

MAX_ENTRIES = 1000


@dataclass
class NetworkEntry:
    reqid: int
    method: str
    url: str
    resource_type: str
    request_headers: dict[str, str]
    post_data: str | None
    status: int | None = None
    response_headers: dict[str, str] | None = None
    timestamp: float = field(default_factory=time.time)
    _response_ref: Any = field(default=None, repr=False)


class NetworkMonitor:
    def __init__(self) -> None:
        self._entries: deque[NetworkEntry] = deque(maxlen=MAX_ENTRIES)
        self._preserved: deque[NetworkEntry] = deque(maxlen=MAX_ENTRIES)
        self._next_reqid: int = 0
        self._pending: dict[int, NetworkEntry] = {}

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
        self._pending[id(request)] = entry

    def _on_response(self, response: Response) -> None:
        entry = self._pending.pop(id(response.request), None)
        if entry is None:
            return
        entry.status = response.status
        entry.response_headers = dict(response.headers)
        entry._response_ref = response

    def _on_request_failed(self, request: Request) -> None:
        entry = self._pending.pop(id(request), None)
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
        ref = entry._response_ref
        if ref is None:
            return None
        try:
            body = await ref.text()
        except Exception:
            logger.debug("Failed to read response body for reqid=%d", entry.reqid, exc_info=True)
            return None
        if len(body) > max_size:
            return body[:max_size] + f"\n... [truncated, {len(body)} total chars]"
        return body
