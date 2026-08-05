from __future__ import annotations

import asyncio
import contextlib
import itertools
from typing import TYPE_CHECKING, Any

from camoufox_mcp.deadlines import bounded
from camoufox_mcp.dom.errors import DeadContextError, is_dead_context
from camoufox_mcp.dom.source import DISPATCH, OPS, seeded_store
from camoufox_mcp.dom.waiting import DISPOSE_TIMEOUT, OP_TIMEOUT

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import EvaluatablePage, JsHandle

# How many uids one store may mint before its numbers reach the next store's block.
#
# A store numbers its elements from its seed upward, and every store in the process
# gets the next block, so 2 stores never hand the same string to 2 different
# elements. That is the whole point: without it every tab and every document
# restarts at ``e0``, and a uid held from one of them silently names a valid but
# different element in another, which is a wrong click reported as a success.
#
# 100,000 is 66 times the default node cap of one capture, so reaching the end of a
# block needs a document to show 100,000 distinct elements to this server. The price
# of the block is uid width: the second document of a session numbers from
# ``e100000``, which is 5 characters more per snapshot line than ``e0``.
UID_BLOCK = 100_000

# Process-wide, so blocks stay disjoint across tabs, across documents and across
# every profile a daemon serves from the same process.
_uid_seeds = itertools.count(0, UID_BLOCK)


async def _release(handle: JsHandle) -> None:
    """Release one handle. Bounded, silent, and never raises.

    Releasing is best effort by nature: the handle may belong to an execution context
    that a navigation already destroyed, or to a tab that is already gone, and
    neither is a failure worth reporting to the caller who happened to trigger it.
    """
    with contextlib.suppress(Exception):
        await bounded(handle.dispose(), DISPOSE_TIMEOUT)


class ElementRegistry:
    """The uid namespace of one tab: a page-heap element table behind one handle.

    The handle IS the document generation marker. It dies with its execution
    context, so a cross-document navigation invalidates every uid for free while a
    same-document navigation preserves them. Nothing is written to the page DOM.

    Every store the process builds numbers from its own block (see
    :data:`UID_BLOCK`), so a uid belongs to exactly 1 tab and 1 document: used
    anywhere else it is simply absent from that store's table and raises the
    mandated stale-uid error instead of naming whatever element happens to hold that
    number there.
    """

    def __init__(self, page: EvaluatablePage, *, target_closed: type[BaseException]) -> None:
        self._page = page
        self._handle: JsHandle | None = None
        self._retired: list[JsHandle] = []
        self._lock = asyncio.Lock()
        self._target_closed = target_closed

    async def call(
        self, op: str, arg: dict[str, Any] | None = None, *, timeout: float = OP_TIMEOUT
    ) -> Any:
        """Run one page-side operation and return its plain JSON result.

        Raises ``TargetClosedError`` (by type, never folded into a stale-uid error),
        ``TimeoutError`` when the page did not answer in time, or the internal
        ``DeadContextError`` when the execution context is gone. No operation is
        ever re-executed here: side effects must not be replayed.

        Any other failure is re-raised unchanged and the store is left standing. A
        dropped store costs the tab its whole table, so every uid the caller holds
        goes stale at once; only a genuinely dead context earns that, because there
        the uids are gone whatever we do.
        """
        if op not in OPS:
            raise ValueError(f"unknown page operation '{op}'")
        payload: dict[str, Any] = {**(arg or {}), "op": op}
        async with self._lock:
            await self._release_retired()
            try:
                handle = self._handle
                if handle is None:
                    handle = self._handle = await bounded(
                        self._page.evaluate_handle(seeded_store(next(_uid_seeds))), timeout
                    )
                return await bounded(handle.evaluate(DISPATCH, payload), timeout)
            except self._target_closed:
                # Dropped, not retired: a closed target has already freed everything
                # the tab held, so asking it to release anything can only fail.
                self._handle = None
                raise
            except TimeoutError as exc:
                raise TimeoutError(f"page script did not answer within {timeout:.0f}s") from exc
            except Exception as exc:
                if not is_dead_context(exc):
                    raise
                await self._drop()
                raise DeadContextError(op) from exc

    def forget(self) -> None:
        """Retire the current handle without any I/O.

        Called from the tab's ``domcontentloaded`` callback, which is synchronous and
        therefore cannot await, so the release is deferred rather than skipped: the
        retired handle is released under the lock by the next operation, or by
        :meth:`dispose` if no operation follows. Deferring is what keeps a release
        from overtaking an operation still in flight against the previous document,
        which would fail that operation with a missing-object protocol error instead
        of the mandated stale-uid string.
        """
        handle, self._handle = self._handle, None
        if handle is not None:
            self._retired.append(handle)

    async def dispose(self) -> None:
        """Release every handle this store still owns. Never raises.

        Called by ``Page.close()`` while the tab is still open, so this is the last
        point at which a release can reach a live target.
        """
        await self._release_retired()
        await self._drop()

    async def _release_retired(self) -> None:
        """Release what :meth:`forget` retired. Never raises.

        At most one handle is ever waiting here: a handle is built only when the slot
        is empty, and every build drains this list first.
        """
        while self._retired:
            await _release(self._retired.pop())

    async def _drop(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            await _release(handle)
