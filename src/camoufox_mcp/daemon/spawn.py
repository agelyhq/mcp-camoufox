from __future__ import annotations

import fcntl
import logging
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx

from camoufox_mcp.daemon.errors import DaemonSpawnError
from camoufox_mcp.daemon.identity import health_matches_identity, local_identity

if TYPE_CHECKING:
    from camoufox_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_BASE_URL = "http://camoufox-daemon"
_PROBE_TIMEOUT_S = 2.0
_SPAWN_LOCK_DEADLINE_S = 20.0
_HEALTHY_DEADLINE_S = 20.0
_SOCKET_REMOVAL_DEADLINE_S = 15.0
_POLL_INTERVAL_S = 0.2


def ensure_daemon(config: ServerConfig) -> None:
    """Guarantee a code-matching daemon is listening on the UDS before proxying.

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
            _wait_socket_removed(config)
        else:
            print(
                "camoufox-mcp: reusing a daemon running different code (has active "
                "sessions; not restarting it)",
                file=sys.stderr,
            )
            return
    _spawn_locked(config, identity)


def _probe_health(config: ServerConfig) -> dict | None:
    if not config.daemon_socket_path.exists():
        return None
    try:
        with _uds_client(config) as client:
            response = client.get(f"{_BASE_URL}/health")
    except (httpx.HTTPError, OSError):
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _uds_client(config: ServerConfig) -> httpx.Client:
    transport = httpx.HTTPTransport(uds=str(config.daemon_socket_path))
    return httpx.Client(transport=transport, timeout=_PROBE_TIMEOUT_S)


def _request_shutdown(config: ServerConfig) -> None:
    try:
        with _uds_client(config) as client:
            client.post(f"{_BASE_URL}/shutdown")
    except (httpx.HTTPError, OSError):
        logger.debug("shutdown request to daemon failed", exc_info=True)


def _wait_socket_removed(config: ServerConfig) -> None:
    """Block until the old daemon has removed its socket FILE, then return.

    A dead health probe is not enough: uvicorn closes the listening socket at the
    very start of ``Server.shutdown()`` (so ``_probe_health`` goes None seconds early),
    but runs the ASGI lifespan teardown afterwards and never unlinks the uds. The file
    is removed only by the daemon's own ``_cleanup_socket()`` as its final act, once
    ``asyncio.run()`` has returned. Waiting for the file to actually disappear
    guarantees the predecessor is fully inert before we spawn a successor at the same
    path — otherwise the dying daemon's late unlink would remove the new daemon's
    freshly bound socket.
    """
    deadline = time.monotonic() + _SOCKET_REMOVAL_DEADLINE_S
    while time.monotonic() < deadline:
        if not config.daemon_socket_path.exists():
            return
        time.sleep(_POLL_INTERVAL_S)


def _spawn_locked(config: ServerConfig, identity: tuple[str, str]) -> None:
    config.ensure_daemon_dir()  # 0o700 parent gates the lock/socket/log before spawn
    lock_fd = os.open(str(config.daemon_lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _acquire_lock(lock_fd, config)
        # Another proxy may have spawned a matching daemon while we waited.
        health = _probe_health(config)
        if health is not None and health_matches_identity(health, identity):
            return
        _unlink_stale_socket(config)
        _popen_daemon(config)
        _wait_healthy(config, identity)
    finally:
        os.close(lock_fd)  # releasing the fd releases the flock


def _acquire_lock(lock_fd: int, config: ServerConfig) -> None:
    deadline = time.monotonic() + _SPAWN_LOCK_DEADLINE_S
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            if time.monotonic() >= deadline:
                raise DaemonSpawnError(
                    f"timed out waiting for the daemon spawn lock {config.daemon_lock_path}"
                ) from exc
            time.sleep(_POLL_INTERVAL_S)


def _unlink_stale_socket(config: ServerConfig) -> None:
    try:
        config.daemon_socket_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.debug("could not unlink stale socket", exc_info=True)


def _popen_daemon(config: ServerConfig) -> None:
    # daemon_dir already exists (0o700) via ensure_daemon_dir in _spawn_locked.
    log_file = open(config.daemon_log_path, "ab")  # noqa: SIM115 (child owns the fd)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "camoufox_mcp.daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            # Sanctioned exception to the config.py env rule: the child daemon
            # re-derives its own ServerConfig from these inherited CAMOUFOX_* vars.
            env=os.environ.copy(),
        )
    finally:
        log_file.close()


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
