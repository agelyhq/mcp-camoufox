from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx
from filelock import FileLock, Timeout

from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.endpoint import IS_WINDOWS
from camoufox_mcp.daemon.errors import DaemonSpawnError
from camoufox_mcp.daemon.identity import local_identity

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.daemon.endpoint import DaemonEndpoint
    from camoufox_mcp.daemon.identity import DaemonIdentity

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 2.0
_SPAWN_LOCK_DEADLINE_S = 20.0
_HEALTHY_DEADLINE_S = 20.0
ADDRESS_REMOVAL_DEADLINE_S = 15.0
_POLL_INTERVAL_S = 0.2


def ensure_daemon(config: ServerConfig, endpoint: DaemonEndpoint) -> None:
    """Guarantee a code-matching daemon is listening before proxying.

    Runs at proxy start and again whenever a request finds the daemon gone. A healthy,
    matching daemon is reused as-is; a healthy but mismatched idle daemon is shut down
    and replaced; anything else is (re)spawned under an exclusive file lock so
    concurrent proxies never double-spawn.
    """
    identity = local_identity(config)
    health = probe_health(config, endpoint)
    if health is not None:
        if identity.matches(health):
            return
        if int(health.get("active_sessions", 0)) > 0:
            _warn_reusing_mismatched("has active sessions")
            return
        logger.info("Replacing idle mismatched daemon")
        _request_shutdown(config, endpoint)
        _wait_unpublished(config, endpoint)
    spawn_locked(config, endpoint, identity)


def _warn_reusing_mismatched(reason: str) -> None:
    print(
        f"mcp-camoufox: reusing a daemon running different code ({reason}; not restarting it)",
        file=sys.stderr,
    )


def probe_health(config: ServerConfig, endpoint: DaemonEndpoint) -> dict | None:
    conn = endpoint.resolve(config)
    if conn is None:
        return None
    try:
        with endpoint.sync_client(conn, timeout=_PROBE_TIMEOUT_S) as client:
            response = client.get("/health")
    except (httpx.HTTPError, OSError):
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _request_shutdown(config: ServerConfig, endpoint: DaemonEndpoint) -> None:
    conn = endpoint.resolve(config)
    if conn is None:
        return
    try:
        with endpoint.sync_client(conn) as client:
            client.post("/shutdown")
    except (httpx.HTTPError, OSError):
        logger.debug("shutdown request to daemon failed", exc_info=True)


def _wait_unpublished(config: ServerConfig, endpoint: DaemonEndpoint) -> None:
    """Block until the old daemon has withdrawn its address advert, then return.

    A dead health probe is not enough: uvicorn stops answering seconds before the
    daemon's own final cleanup removes the socket (POSIX) or endpoint file (Windows).
    Waiting for the advert to actually disappear guarantees the predecessor is fully
    inert before a successor is spawned at the same location.
    """
    deadline = time.monotonic() + ADDRESS_REMOVAL_DEADLINE_S
    while time.monotonic() < deadline:
        if endpoint.resolve(config) is None:
            return
        time.sleep(_POLL_INTERVAL_S)


def spawn_locked(config: ServerConfig, endpoint: DaemonEndpoint, identity: DaemonIdentity) -> None:
    paths.ensure_daemon_dir(config)  # 0o700 parent gates the lock and log before spawn
    lock_path = paths.lock_path(config)
    lock = FileLock(str(lock_path))
    try:
        lock.acquire(timeout=_SPAWN_LOCK_DEADLINE_S, poll_interval=_POLL_INTERVAL_S)
    except Timeout as exc:
        raise DaemonSpawnError(f"timed out waiting for the daemon spawn lock {lock_path}") from exc
    try:
        # Another proxy may have spawned a matching daemon while we waited.
        health = probe_health(config, endpoint)
        if health is not None and identity.matches(health):
            return
        if not _reclaim_advert(config, endpoint):
            _warn_reusing_mismatched("it still answers on the control channel")
            return
        _popen_daemon(config)
        _wait_healthy(config, endpoint, identity)
    finally:
        lock.release()


def _reclaim_advert(config: ServerConfig, endpoint: DaemonEndpoint) -> bool:
    """Free the control address for a fresh bind, never at a live daemon's expense.

    A shutdown request the daemon refused (a session landed after the health probe
    said it was idle) leaves it running and reachable only through this advert.
    Removing it there would strand its browsers, so the advert is dropped only when
    nothing answers on it AND it is still the exact one just inspected. ``False``
    means the address belongs to a daemon that is still alive: reuse it, do not
    replace it.
    """
    advert_id = endpoint.advert_id(config)
    if advert_id is None:
        return True
    if probe_health(config, endpoint) is not None:
        logger.warning("Daemon at the control address is still serving; keeping its advert")
        return False
    return endpoint.cleanup_if_owned(config, advert_id)


def _popen_daemon(config: ServerConfig) -> None:
    # daemon_dir already exists (0o700) via ensure_daemon_dir in spawn_locked.
    log_file = open(paths.log_path(config), "ab")  # noqa: SIM115 (child owns the fd)
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


def _wait_healthy(config: ServerConfig, endpoint: DaemonEndpoint, identity: DaemonIdentity) -> None:
    deadline = time.monotonic() + _HEALTHY_DEADLINE_S
    while time.monotonic() < deadline:
        health = probe_health(config, endpoint)
        if health is not None and identity.matches(health):
            return
        time.sleep(_POLL_INTERVAL_S)
    raise DaemonSpawnError(
        f"daemon did not become healthy within {_HEALTHY_DEADLINE_S:.0f}s.\n"
        f"--- {paths.log_path(config)} (tail) ---\n{log_tail(config)}"
    )


def log_tail(config: ServerConfig, lines: int = 40) -> str:
    """The last ``lines`` of the detached daemon's log, or why there are none.

    Public because a spawn failure is not the only failure that is unreadable without
    it: the tests' daemon harness folds the same tail into an assertion message, since
    the log lives in a data dir that is gone by the time anyone reads a CI report.
    """
    try:
        text = paths.log_path(config).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no daemon.log)"
    return "\n".join(text.splitlines()[-lines:])
