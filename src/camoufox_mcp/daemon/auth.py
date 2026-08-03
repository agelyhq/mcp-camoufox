from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class TokenAuthMiddleware:
    """Reject any HTTP request that does not present the daemon's bearer token.

    On Windows the daemon's control channel is a ``127.0.0.1`` TCP socket, which
    any local process can reach — there is no Unix-socket file mode to gate it. A
    per-daemon secret guards every route instead (``/health``, ``/shutdown`` and
    the MCP endpoint). POSIX daemons keep their 0o600 Unix socket and never mount
    this middleware.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        # Compared as bytes: decoding first would make compare_digest raise
        # TypeError on any header byte >= 0x80 instead of answering 401.
        provided = headers.get(b"authorization", b"")
        if not secrets.compare_digest(provided, self._expected):
            await PlainTextResponse("unauthorized", status_code=401)(scope, receive, send)
            return
        await self._app(scope, receive, send)
