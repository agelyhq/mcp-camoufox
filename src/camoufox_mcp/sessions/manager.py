from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from camoufox_mcp.sessions.errors import ProfileInUseError
from camoufox_mcp.sessions.init_options import SessionInitOptions
from camoufox_mcp.sessions.session import Session

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)


class SessionManager:
    """Owns the live sessions keyed by profile name and their cross-process locks."""

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, FileLock] = {}
        self._create_lock = asyncio.Lock()

    async def get_or_create(self, profile: str, **overrides: object) -> Session:
        """Return the active session for ``profile`` or lazily create one.

        ``overrides`` (fingerprint_os, viewport_width, viewport_height, locale,
        block_images, block_webrtc) are applied only at creation time and ignored
        when the profile is already active. Raises :class:`ProfileInUseError` if the
        profile is locked by another OS process.
        """
        existing = self._sessions.get(profile)
        if existing is not None:
            return existing

        async with self._create_lock:
            existing = self._sessions.get(profile)
            if existing is not None:
                return existing

            lock = self._acquire_lock(profile)
            try:
                opts = SessionInitOptions.resolve(self._config.session_defaults, **overrides)  # type: ignore[arg-type]
                session = await Session.create(config=self._config, profile=profile, opts=opts)
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

    async def close_session(self, profile: str) -> None:
        """Close the browser for ``profile`` and release its lock. Idempotent.

        The persistent profile directory is preserved on disk for reuse.
        """
        session = self._sessions.pop(profile, None)
        lock = self._locks.pop(profile, None)
        if session is not None:
            await session.close()
        if lock is not None:
            lock.release()

    async def shutdown(self) -> None:
        for profile in list(self._sessions):
            try:
                await self.close_session(profile)
            except Exception:
                logger.warning("Failed to close session %s during shutdown", profile, exc_info=True)

    def _acquire_lock(self, profile: str) -> FileLock:
        self._config.profiles_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self._config.profiles_dir / f"{profile}.lock"))
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise ProfileInUseError(profile) from exc
        return lock
