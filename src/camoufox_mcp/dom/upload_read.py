"""The disk half of ``upload_file``: asking the kernel about a resolved path, then reading it.

Pure Python, no page object: the file never reaches Playwright or Firefox, so every
failure on this path is one this process can name precisely, and each refusal is a
sentence carrying strerror, errno and, when it differs from what was typed, the path
that was checked. The text-to-path half is :mod:`camoufox_mcp.dom.upload_path`; this
module only imports its Win32 constants, to say when a length was the cause.

The read is the one operation here with a clock: it runs on a daemon thread under
``READ_TIMEOUT``, so a cloud placeholder hydrating on first open or a network share
that stopped answering neither blocks the loop nor holds the process open.
"""

from __future__ import annotations

import asyncio
import errno
import ntpath
import os
import stat
import threading
from pathlib import PurePath, PureWindowsPath
from typing import Protocol

from camoufox_mcp.deadlines import bounded
from camoufox_mcp.dom.upload_path import EXTENDED_PREFIX, MAX_PATH
from camoufox_mcp.dom.waiting import READ_TIMEOUT, render_deadline

# ``st_file_attributes`` bits of a cloud placeholder: the entry is a real regular file
# with its full logical size, and the bytes are fetched on the first open.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_PLACEHOLDER_BITS = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

# The prefix of the thread that reads an upload; a test looks it up by name.
READER_THREAD_PREFIX = "upload-read:"


class ReadablePath(Protocol):
    """What ``read_upload`` asks of a path: a name and the bytes behind it."""

    @property
    def name(self) -> str: ...

    def read_bytes(self) -> bytes: ...


def stat_upload(raw: str, path: PurePath) -> os.stat_result:
    """``os.stat`` of the resolved path, every refusal turned into a sentence.

    ``Path.is_file`` swallows ENOENT, ENOTDIR and the Win32 "invalid name" errors alike,
    which collapsed a bad name, a missing file and a denied directory into one line.
    """
    try:
        st = os.stat(path)
    except OSError as exc:
        raise ValueError(
            f"cannot read '{raw}': {_described(exc)}{_checked(raw, path)}{_length_note(path)}"
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"'{raw}' is not a regular file{_checked(raw, path)}")
    check_placeholder(st, raw)
    return st


def check_placeholder(st: os.stat_result, raw: str) -> None:
    """Refuse a cloud placeholder before the read that would try to hydrate it.

    ``stat`` reports the full logical size of a OneDrive Files-On-Demand entry without
    fetching it; the first ``open`` does, and blocks for as long as the sync client
    takes, or fails when it is paused. On a filesystem without the attribute the field
    is absent and nothing is refused.
    """
    attributes = getattr(st, "st_file_attributes", 0)
    if attributes & _PLACEHOLDER_BITS:
        raise ValueError(
            f"'{raw}' is a OneDrive/cloud placeholder not downloaded on this machine; "
            f"right-click it > 'Always keep on this device' and retry"
        )


async def read_upload(raw: str, path: ReadablePath) -> bytes:
    """The file's bytes, read on a thread of their own and under ``READ_TIMEOUT``.

    The read runs on a daemon thread, not the loop's executor: a read that never
    returns (a network share that stopped answering) is abandoned when the budget
    expires, and a daemon thread is one neither the loop's shutdown nor the
    interpreter's exit waits for, so a wedged file cannot hold the server open after
    its client disconnected. The price is that thread staying parked until the kernel
    gives up, which nothing here can shorten.

    ``TimeoutError`` is caught before ``OSError`` because it is a subclass of it: the
    other order rendered an expired budget as ``cannot read ...: TimeoutError``. A read
    that fails after a passing ``stat`` is what a sharing violation looks like on
    Windows (``EACCES`` with no ``winerror``), so that errno gets the hint on a Windows
    path; on a POSIX one the same errno is a plain permission denial and gets none.
    """
    try:
        return await bounded(_read_on_daemon_thread(path), READ_TIMEOUT)
    except TimeoutError as exc:
        raise TimeoutError(
            f"reading '{raw}' did not finish within {render_deadline(READ_TIMEOUT)}; "
            f"a cloud-synced or network file may still be downloading"
        ) from exc
    except OSError as exc:
        raise ValueError(f"cannot read '{raw}': {_described(exc)}{_lock_hint(exc, path)}") from exc


async def _read_on_daemon_thread(path: ReadablePath) -> bytes:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bytes] = loop.create_future()

    def deliver(outcome: bytes | Exception) -> None:
        # Runs on the loop. The future is already cancelled when the budget expired
        # first, and a cancelled future refuses a result: the late outcome is dropped.
        if future.done():
            return
        if isinstance(outcome, Exception):
            future.set_exception(outcome)
        else:
            future.set_result(outcome)

    def work() -> None:
        try:
            outcome: bytes | Exception = path.read_bytes()
        except Exception as exc:
            outcome = exc
        try:
            loop.call_soon_threadsafe(deliver, outcome)
        except RuntimeError:
            # The loop is closed: the server exited while this read was parked, and
            # nobody is left to want the outcome.
            return

    threading.Thread(target=work, name=f"{READER_THREAD_PREFIX}{path.name}", daemon=True).start()
    return await future


def _checked(raw: str, path: PurePath) -> str:
    """Name the resolved path once it is not the typed one, so a bad expansion shows."""
    return "" if str(path) == raw.strip() else f" (checked '{path}')"


def _described(exc: OSError) -> str:
    """``strerror (errno N[, winerror N])``: the words and both numbers, never a repr."""
    winerror = getattr(exc, "winerror", None)
    win = f", winerror {winerror}" if winerror else ""
    return f"{exc.strerror or type(exc).__name__} (errno {exc.errno}{win})"


def _lock_hint(exc: OSError, path: ReadablePath) -> str:
    """The sharing-violation reading of ``EACCES``, a Win32 fact and nothing else's."""
    if not isinstance(path, PureWindowsPath) or exc.errno != errno.EACCES:
        return ""
    return "; the file may be open in another program: close it and retry"


def _length_note(path: PurePath) -> str:
    """Name the length once it is the plausible cause of a not-found on Windows.

    Measured on the resolved path, the one ``stat`` was asked about, without the
    ``\\\\?\\`` prefix that ``win32_extended`` adds at or past the ceiling, and after
    the same ``normpath`` it measured; the typed string carries quotes, a scheme or an
    unexpanded ``%VAR%`` and has no length of its own to speak of.
    """
    if not isinstance(path, PureWindowsPath):
        return ""
    text = str(path)
    extended = text.startswith(EXTENDED_PREFIX)
    length = len(text) - len(EXTENDED_PREFIX) if extended else len(ntpath.normpath(text))
    if length < MAX_PATH:
        return ""
    tried = ", tried in the \\\\?\\ form" if extended else ""
    return f"; the path is {length} characters, past Win32's {MAX_PATH} limit{tried}"
