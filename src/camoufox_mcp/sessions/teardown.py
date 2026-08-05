from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from camoufox_mcp.deadlines import bounded

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)

# Closing is the one path that must always finish. Firefox can stop answering Juggler
# while its process stays alive (see launch.py), and none of these calls carries a
# deadline of its own, so an unbounded await here wedges close_session and, through
# shutdown(), the process exit. A tab that will not answer is abandoned instead: the
# browser process is killed a moment later when the context and the driver go down.
TAB_CLOSE_TIMEOUT = 10.0
CONTEXT_CLOSE_TIMEOUT = 15.0
DRIVER_STOP_TIMEOUT = 10.0


async def quietly(step: str, work: Coroutine[Any, Any, Any], timeout: float) -> None:
    """Run one teardown step under a deadline; log and swallow every failure.

    Teardown runs after the caller has already been told the session is going away,
    so a step that fails must not stop the remaining ones: the driver process behind
    them is what actually leaks.
    """
    try:
        await bounded(work, timeout)
    except Exception:
        logger.debug("%s failed during teardown", step, exc_info=True)
