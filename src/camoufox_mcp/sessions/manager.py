from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from camoufox_mcp.profile_name import validate_profile
from camoufox_mcp.sessions.errors import ProfileInUseError
from camoufox_mcp.sessions.init_options import SessionInitOptions
from camoufox_mcp.sessions.session import Session

if TYPE_CHECKING:
    from collections.abc import Callable

    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

# ``reason`` handed to the close observer. A tool-driven close is by far the common
# case: measured over the production logs, 147 of 159 profiles ended on an explicit
# ``close_session`` call, which is exactly why a marker emitted only from
# ``shutdown()`` was never observed once.
CLOSE_REASON_TOOL = "close_session"
CLOSE_REASON_SHUTDOWN = "shutdown"


class SessionManager:
    """Owns the live sessions keyed by profile name and their cross-process locks.

    ``on_closed(profile, reason)`` is notified whenever a browser goes away. It is a
    plain observer so this class stays about lifecycle: what a closure is worth
    recording, and in which schema, belongs to whoever composed the server.
    """

    def __init__(
        self, config: ServerConfig, on_closed: Callable[[str, str], None] | None = None
    ) -> None:
        self._config = config
        self._on_closed = on_closed
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, FileLock] = {}
        self._create_locks: dict[str, asyncio.Lock] = {}

    async def get_or_create(self, profile: str, opts: SessionInitOptions | None = None) -> Session:
        """Return the active session for ``profile`` or lazily create one.

        ``opts`` shapes the browser at creation only and is ignored when the profile
        is already active; ``None`` means the server-wide defaults. Raises
        :class:`ProfileInUseError` if the profile is locked by another OS process.

        This is the single point where a profile name becomes a filesystem path (the
        lock below, then ``ensure_profile_dir`` inside ``Session.create``), so the
        name is validated here, before either path is built. Raises
        :class:`InvalidProfileNameError` for anything that is not a safe token.
        """
        validate_profile(profile)

        existing = self._sessions.get(profile)
        if existing is not None:
            return existing

        async with self._creation_lock(profile):
            existing = self._sessions.get(profile)
            if existing is not None:
                return existing

            lock = self._acquire_lock(profile)
            try:
                session = await Session.create(
                    config=self._config,
                    profile=profile,
                    opts=opts or SessionInitOptions.resolve(self._config.session_defaults),
                )
            except Exception:
                lock.release()
                raise

            self._sessions[profile] = session
            self._locks[profile] = lock
            return session

    def get(self, profile: str) -> Session | None:
        return self._sessions.get(profile)

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def active_count(self) -> int:
        """Number of live sessions, used by the daemon /health route and TTL watchdog."""
        return len(self._sessions)

    async def close_session(self, profile: str, *, reason: str = CLOSE_REASON_TOOL) -> None:
        """Close the browser for ``profile`` and release its lock. Idempotent.

        The persistent profile directory is preserved on disk for reuse.

        Every closure the server performs passes through here, so this is also where
        the close observer is notified, with ``reason`` naming the trigger. It runs in
        a ``finally`` and after the lock release, so a browser that fails to shut down
        cleanly still leaves a record.
        """
        session = self._sessions.pop(profile, None)
        lock = self._locks.pop(profile, None)
        try:
            if session is not None:
                await session.close()
        finally:
            if lock is not None:
                lock.release()
            self._forget_creation_lock(profile)
            if session is not None:
                self._notify_closed(profile, reason)

    async def shutdown(self) -> None:
        """Close every live session. Only reached when the process exits gracefully."""
        for profile in list(self._sessions):
            try:
                await self.close_session(profile, reason=CLOSE_REASON_SHUTDOWN)
            except Exception:
                logger.warning("Failed to close session %s during shutdown", profile, exc_info=True)

    def _creation_lock(self, profile: str) -> asyncio.Lock:
        """The launch lock of one profile, created on demand.

        Per profile, never process-wide: a cold Camoufox launch takes seconds, and a
        single shared lock made every other client's first call queue behind it, which
        in daemon mode is every client the process serves. Two launches may now
        overlap. Each one still gets a private environment copy
        (:meth:`ServerConfig.launch_env`), which is what keeps a ``headless='virtual'``
        launch's throwaway ``DISPLAY`` inside that launch instead of repointing the
        whole process at a 1x1 X server.
        """
        lock = self._create_locks.get(profile)
        if lock is None:
            lock = self._create_locks[profile] = asyncio.Lock()
        return lock

    def _forget_creation_lock(self, profile: str) -> None:
        """Drop a profile's launch lock once nobody holds it.

        Kept so a long-lived daemon does not accumulate one lock per profile name it
        has ever served. A held lock is left alone: its holder is mid-launch, and its
        waiters must not be handed a different object to wait on.
        """
        lock = self._create_locks.get(profile)
        if lock is not None and not lock.locked():
            del self._create_locks[profile]

    def _notify_closed(self, profile: str, reason: str) -> None:
        """Tell the observer a browser is gone. Best effort: closing must not fail."""
        if self._on_closed is None:
            return
        try:
            self._on_closed(profile, reason)
        except Exception:
            logger.debug("close observer failed for %s", profile, exc_info=True)

    def _acquire_lock(self, profile: str) -> FileLock:
        self._config.ensure_profiles_dir()
        lock = FileLock(str(self._config.profiles_dir / f"{profile}.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise ProfileInUseError(profile) from exc
        return lock
