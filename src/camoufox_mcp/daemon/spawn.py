from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx
from filelock import FileLock, Timeout

from camoufox_mcp.daemon.endpoint import ENDPOINT, IS_WINDOWS
from camoufox_mcp.daemon.errors import DaemonSpawnError
from camoufox_mcp.daemon.identity import health_matches_identity, local_identity

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 2.0
_SPAWN_LOCK_DEADLINE_S = 20.0
_HEALTHY_DEADLINE_S = 20.0
_ADDRESS_REMOVAL_DEADLINE_S = 15.0
_POLL_INTERVAL_S = 0.2


def ensure_daemon(config: ServerConfig) -> None:
    """Guarantee a code-matching daemon is listening before proxying.

    Runs once at proxy start. A healthy, matching daemon is reused as-is; a healthy
    but mismatched idle daemon is shut down and replaced; anything else is (re)spawned
    under an exclusive file lock so concurrent proxies never double-spawn.
    """
    identity = local_identity()
    health = _probe_health(config)
    if health is not None:
        if health_matches_identity(health, identity):
            return
        if int(health.get("active_sessions", 0)) == 0:
            logger.info("Replacing idle mismatched daemon")
            _request_shutdown(config)
            _wait_unpublished(config)
        else:
            print(
                "camoufox-mcp: reusing a daemon running different code (has active "
                "sessions; not restarting it)",
                file=sys.stderr,
            )
            return
    _spawn_locked(config, identity)


def _probe_health(config: ServerConfig) -> dict | None:
    conn = ENDPOINT.resolve(config)
    if conn is None:
        return None
    try:
        with ENDPOINT.sync_client(conn, timeout=_PROBE_TIMEOUT_S) as client:
            response = client.get("/health")
    except (httpx.HTTPError, OSError):
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _request_shutdown(config: ServerConfig) -> None:
    conn = ENDPOINT.resolve(config)
    if conn is None:
        return
    try:
        with ENDPOINT.sync_client(conn) as client:
            client.post("/shutdown")
    except (httpx.HTTPError, OSError):
        logger.debug("shutdown request to daemon failed", exc_info=True)


def _wait_unpublished(config: ServerConfig) -> None:
    """Block until the old daemon has withdrawn its address advert, then return.

    A dead health probe is not enough: uvicorn stops answering seconds before the
    daemon's own final cleanup removes the socket (POSIX) or endpoint file (Windows).
    Waiting for the advert to actually disappear guarantees the predecessor is fully
    inert before a successor is spawned at the same location.
    """
    deadline = time.monotonic() + _ADDRESS_REMOVAL_DEADLINE_S
    while time.monotonic() < deadline:
        if ENDPOINT.resolve(config) is None:
            return
        time.sleep(_POLL_INTERVAL_S)


def _spawn_locked(config: ServerConfig, identity: tuple[str, str]) -> None:
    config.ensure_daemon_dir()  # 0o700 parent gates the lock/advert/log before spawn
    lock = FileLock(str(config.daemon_lock_path))
    try:
        lock.acquire(timeout=_SPAWN_LOCK_DEADLINE_S, poll_interval=_POLL_INTERVAL_S)
    except Timeout as exc:
        raise DaemonSpawnError(
            f"timed out waiting for the daemon spawn lock {config.daemon_lock_path}"
        ) from exc
    try:
        # Another proxy may have spawned a matching daemon while we waited.
        health = _probe_health(config)
        if health is not None and health_matches_identity(health, identity):
            return
        ENDPOINT.cleanup(config)  # drop any stale advert from a crashed daemon
        _popen_daemon(config)
        _wait_healthy(config, identity)
    finally:
        lock.release()


def _popen_daemon(config: ServerConfig) -> None:
    # daemon_dir already exists (0o700) via ensure_daemon_dir in _spawn_locked.
    log_file = open(config.daemon_log_path, "ab")  # noqa: SIM115 (child owns the fd)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "camoufox_mcp.daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            # Sanctioned exception to the config.py env rule: the child daemon
            # re-derives its own ServerConfig from these inherited CAMOUFOX_* vars.
            env=os.environ.copy(),
            **_detach_kwargs(),
        )
    finally:
        log_file.close()


def _detach_kwargs() -> dict:
    """Popen flags that fully detach the daemon from the spawning process."""
    if IS_WINDOWS:
        # DETACHED_PROCESS drops the console; CREATE_NEW_PROCESS_GROUP shields the
        # daemon from the caller's Ctrl-C/Ctrl-Break so it outlives that process.
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _wait_healthy(config: ServerConfig, identity: tuple[str, str]) -> None:
    deadline = time.monotonic() + _HEALTHY_DEADLINE_S
    while time.monotonic() < deadline:
        health = _probe_health(config)
        if health is not None and health_matches_identity(health, identity):
            return
        time.sleep(_POLL_INTERVAL_S)
    raise DaemonSpawnError(
        f"daemon did not become healthy within {_HEALTHY_DEADLINE_S:.0f}s.\n"
        f"--- {config.daemon_log_path} (tail) ---\n{_log_tail(config)}"
    )


def _log_tail(config: ServerConfig, lines: int = 40) -> str:
    try:
        text = config.daemon_log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no daemon.log)"
    return "\n".join(text.splitlines()[-lines:])
