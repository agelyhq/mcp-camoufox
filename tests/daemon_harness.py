"""Shared fixture and process helpers for the daemon end-to-end tests.

Every daemon test spawns a real detached process, so teardown has to be pessimistic:
ask it to leave, then kill by pid, then reap. The helpers live here so several test
modules drive the same daemon lifecycle instead of each growing its own copy.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon import paths
from camoufox_mcp.daemon.endpoint import select_endpoint
from camoufox_mcp.daemon.identity import DaemonIdentity
from camoufox_mcp.daemon.socket_path import address_pointer_path, published_socket_path
from camoufox_mcp.daemon.spawn import log_tail, probe_health
from tests.helpers import isolate_camoufox_env
from tests.waits import poll_until_sync

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

IS_WINDOWS = os.name == "nt"

# Enough of daemon.log to carry the shutdown sequence into a failure message, without
# turning a CI report into a transcript. The scan window is wider than what is printed
# because repeated lines are folded first (see _folded_log_tail).
_LOG_TAIL_LINES = 20
_LOG_SCAN_LINES = 200

# The control-channel strategy the tests drive, built once like the daemon and the
# proxy build theirs. Every daemon helper takes it as an argument.
ENDPOINT = select_endpoint()


class Harness:
    """Holds the address-bearing config so teardown can always reach the daemon.

    ``track`` records daemons a test knows about beyond the one currently
    advertised, so an orphan left behind by a failing assertion is still killed.
    """

    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg
        self.pids: set[int] = set()

    def track(self, pid: int) -> None:
        self.pids.add(pid)


def daemon_session(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path | None = None
) -> Iterator[Harness]:
    """Body of the per-test ``daemon_env`` fixture: private data dir, headless, no update.

    A plain generator rather than a fixture, so each test module declares its own
    ``daemon_env`` instead of importing one (an imported fixture reads as a redefinition
    at every test signature that takes it).

    ``data_dir`` is a throwaway temporary directory unless a test needs a specific one
    (a path long enough to overflow ``sun_path``, say); either way it is torn down here,
    so no test hand-rolls the teardown.
    """
    root = Path(tempfile.mkdtemp(prefix="cfxd-")) if data_dir is None else data_dir
    isolate_camoufox_env(monkeypatch, root, CAMOUFOX_DAEMON_TTL="60")

    harness = Harness(ServerConfig.from_env())
    try:
        yield harness
    finally:
        _force_teardown(harness)
        rmtree_retry(root)


def mismatched_identity(config: ServerConfig) -> DaemonIdentity:
    """Identity of a proxy running different code than the daemon it finds.

    The version alone decides it: :meth:`DaemonIdentity.matches` needs all 3 fields to
    agree, so one impossible version is the whole mismatch and the data dir stays the
    real one instead of adding a second, incidental difference.
    """
    return DaemonIdentity(
        version="9.9.9-mismatch",
        code_path="/nowhere",
        data_dir=str(config.data_dir),
    )


def advert_paths(cfg: ServerConfig) -> tuple[Path, ...]:
    """Every file advertising a daemon's address on this platform.

    POSIX publishes 2 of them, and asserting on the socket alone graded the platform
    rather than the product: Python 3.13's asyncio unlinks a closed Unix socket by
    itself, so a daemon that withdrew nothing still looked clean on 3.13 and left its
    address pointer behind on 3.12, which is what the release runner caught.
    """
    if IS_WINDOWS:
        return (paths.endpoint_path(cfg),)
    return (published_socket_path(cfg), address_pointer_path(cfg))


def daemon_diagnostics(cfg: ServerConfig, note: str) -> str:
    """``note``, followed by the evidence a reader needs when they cannot reproduce it.

    A failing daemon assertion used to say only what was expected. On a runner that is
    all anyone gets: the data dir is a per-test temp dir the fixture removes, so
    ``daemon.log`` dies with the run and the next step is a whole new release cycle. The
    state that explains these failures is small, so it goes in the message: which advert
    file is still there, which is not, where the pointer says the daemon was listening,
    and what the daemon last said before it went.

    Meant for the message half of an assertion (``assert cond, daemon_diagnostics(...)``),
    which Python evaluates only when the condition already failed. The happy path reads
    no files.
    """
    lines = [note, f"data dir: {cfg.data_dir}"]
    for path in advert_paths(cfg):
        lines.append(f"advert {path}: {'still there' if path.exists() else 'gone'}")
    if not IS_WINDOWS:
        lines.append(f"address pointer says: {_pointer_contents(cfg)}")
    lines.append(f"--- {paths.log_path(cfg)} (tail) ---")
    lines.append(_folded_log_tail(cfg))
    return "\n".join(lines)


def _folded_log_tail(cfg: ServerConfig) -> str:
    """The tail of daemon.log with runs of one repeated line folded to that line.

    A proxy polls /health every 0.2s while it waits, and uvicorn logs every probe
    identically. On a slow runner those alone overflow any tail worth printing and push
    out the shutdown sequence, which is the part that explains the failure.
    """
    seen = log_tail(cfg, lines=_LOG_SCAN_LINES).splitlines()
    folded = [line for index, line in enumerate(seen) if index == 0 or line != seen[index - 1]]
    return "\n".join(folded[-_LOG_TAIL_LINES:])


def _pointer_contents(cfg: ServerConfig) -> str:
    try:
        return address_pointer_path(cfg).read_text(encoding="utf-8").strip() or "(empty)"
    except OSError:
        return "(no pointer file)"


def control_client(cfg: ServerConfig) -> httpx.Client:
    conn = ENDPOINT.resolve(cfg)
    assert conn is not None, "daemon advertised no address"
    return ENDPOINT.sync_client(conn)


def rmtree_retry(path: Path, deadline: float = 8.0) -> None:
    """Remove the data dir, retrying while Camoufox flushes its profile on exit.

    Firefox keeps writing the profile (sessionstore, telemetry, startupCache) for a
    second or two after Playwright's ``close()`` returns, so a single rmtree can race
    that flush and leave a partial dir behind.
    """
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        shutil.rmtree(path, ignore_errors=True)
        # Let any lingering Firefox content process finish flushing, then confirm
        # the dir stays gone — an immediate re-check would miss a late rewrite.
        time.sleep(0.5)
        if not path.exists():
            return
    shutil.rmtree(path, ignore_errors=True)


def _force_teardown(harness: Harness) -> None:
    """Force-shut the advertised daemon, then hard-kill every pid the test saw."""
    cfg = harness.cfg
    health = probe_health(cfg, ENDPOINT)
    if health is not None:
        if health.get("pid"):
            harness.track(int(health["pid"]))
        with contextlib.suppress(httpx.HTTPError, OSError), control_client(cfg) as client:
            client.post("/shutdown", params={"force": "true"})
        wait_gone(cfg)
    for pid in harness.pids:
        if alive(pid):
            hard_kill(pid)
        reap(cfg, pid)
    for path in advert_paths(cfg):
        with contextlib.suppress(OSError):
            path.unlink()


def alive(pid: int) -> bool:
    if IS_WINDOWS:
        return True  # No cheap liveness check; the kill below is harmless either way.
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def hard_kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        # Windows has no SIGKILL; os.kill with SIGTERM maps to TerminateProcess.
        os.kill(pid, signal.SIGTERM if IS_WINDOWS else signal.SIGKILL)


def wait_gone(cfg: ServerConfig, deadline: float = 15.0) -> bool:
    return poll_until_sync(lambda: probe_health(cfg, ENDPOINT) is None, deadline=deadline)


def wait_advert_gone(cfg: ServerConfig, deadline: float = 10.0) -> bool:
    """Wait for every advert file to disappear, rather than demanding they already have.

    A daemon stops answering, exits, and unlinks its advert, in that order. On a 2-core
    runner those 3 can land whole seconds apart, so asserting the files are gone the
    instant the process is reaped tests the scheduler, not the cleanup. The condition
    asserted is unchanged: the advert must go. Only the "immediately" is dropped.
    """
    return poll_until_sync(
        lambda: not any(path.exists() for path in advert_paths(cfg)), deadline=deadline
    )


def reap(cfg: ServerConfig, pid: int, deadline: float = 5.0) -> bool:
    """Confirm a spawned daemon has actually terminated.

    On POSIX the daemon is a child of this process, so an unreaped exit lingers as a
    zombie that still answers signal 0; ``waitpid`` reaps it. Windows has no zombies
    and no ``waitpid`` for a pid, so a vanished health endpoint is proof of exit.
    """
    if IS_WINDOWS:
        return wait_gone(cfg, deadline)

    def terminated() -> bool:
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        return reaped == pid

    return poll_until_sync(terminated, deadline=deadline, interval=0.05)


def assert_hardened(cfg: ServerConfig) -> None:
    """The freshly bound control channel must be reachable only by its owner."""
    if IS_WINDOWS:
        # No Unix socket file mode on Windows; the bearer token is the boundary, so
        # an unauthenticated request must be refused.
        conn = ENDPOINT.resolve(cfg)
        assert conn is not None
        with httpx.Client(base_url=conn.base_url, timeout=2.0) as raw:
            assert raw.get("/health").status_code == 401
        return
    # The daemon tightens uvicorn's default 0o666 socket mode shortly after bind.
    socket_path = published_socket_path(cfg)
    poll_until_sync(
        lambda: (socket_path.stat().st_mode & 0o777) == 0o600, deadline=2.0, interval=0.05
    )
    assert (socket_path.stat().st_mode & 0o777) == 0o600
