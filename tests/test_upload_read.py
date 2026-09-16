"""What ``upload_file`` answers when the path resolves and the disk then says no.

A missing file, a folder, a read the kernel refuses and a read that never returns each
get their own sentence, and every one is driven through the real tool so the ``@tool``
wrapper's rendering is part of what is asserted. The wedged read is the one scenario
with no public-surface path on Linux (``stat_upload`` refuses everything that is not a
regular file, and a regular file on local disk reads at once), so it is exercised on
``read_upload`` directly with a FIFO nobody writes to.
"""

from __future__ import annotations

import errno
import os
import threading
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.dom import upload_read
from camoufox_mcp.dom.upload_read import READER_THREAD_PREFIX, read_upload
from tests.upload_helpers import TEXT, input_uid, upload
from tests.waits import poll_until_sync

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client

# The wording of an expired read budget, rendered by the wrapper as a Timeout line.
READ_EXPIRED = (
    "Timeout: reading '{typed}' did not finish within {budget}; "
    "a cloud-synced or network file may still be downloading"
)


async def test_missing_file_names_the_path_it_checked(
    client: Client, tmp_path: Path, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``~`` (or ``%VAR%``, or ``file:``) that expanded to the wrong place is only
    correctable when the message says where it went."""
    uid = await input_uid(client, flask_server)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = await upload(client, uid, "~/nowhere.txt")
    assert result == (
        "Error: ValueError: cannot read '~/nowhere.txt': No such file or directory "
        f"(errno {errno.ENOENT}) (checked '{tmp_path / 'nowhere.txt'}')"
    ), result


async def test_a_directory_is_not_a_regular_file(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """A folder passes ``stat`` and is refused by name before any read is attempted."""
    uid = await input_uid(client, flask_server)

    result = await upload(client, uid, str(tmp_path))
    assert result == f"Error: ValueError: '{tmp_path}' is not a regular file", result


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
async def test_unreadable_file_is_on_contract(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """A read that fails after ``stat`` passed is a ``ValueError`` with the errno, never
    an ``OSError`` that earns a traceback in the server log. The exact ``Error:
    ValueError:`` line is the proof: the wrapper renders the exception's own type name,
    so a ``PermissionError`` escaping would read ``Error: PermissionError: [Errno 13]``
    here. On POSIX the line stops at the errno; the "open in another program" reading of
    ``EACCES`` is a Windows-path fact, proved in :mod:`tests.test_upload_win32`."""
    uid = await input_uid(client, flask_server)
    file = tmp_path / "locked.txt"
    file.write_bytes(TEXT)
    file.chmod(0)

    result = await upload(client, uid, str(file))
    assert result == (
        f"Error: ValueError: cannot read '{file}': Permission denied (errno {errno.EACCES})"
    ), result


async def test_a_read_past_its_budget_is_a_timeout_line(
    client: Client, tmp_path: Path, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The expiry renders as ``Timeout: reading ...``, not as a ``cannot read`` line.

    ``READ_TIMEOUT`` is the public budget the read runs under; at zero the clock
    expires before the read starts, on every interpreter, which is what makes a local
    file stand in for a share that stopped answering. ``TimeoutError`` subclasses
    ``OSError``, and the branch that words it was unreachable until the handlers were
    ordered accordingly: this is the test that would have said so.
    """
    uid = await input_uid(client, flask_server)
    file = tmp_path / "slow.txt"
    file.write_bytes(TEXT)
    monkeypatch.setattr(upload_read, "READ_TIMEOUT", 0.0)

    result = await upload(client, uid, str(file))
    assert result == READ_EXPIRED.format(typed=file, budget="0s"), result


async def test_a_wedged_read_is_abandoned_on_a_daemon_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that never returns expires on time and cannot hold the process open.

    Run on the loop's executor, the parked worker was joined at loop shutdown (300 s)
    and again, without a bound, at interpreter exit, so a network share that stopped
    answering mid-upload kept the server alive after its client had gone. The reader
    is a daemon thread instead, found here by name; the FIFO is then given its writer
    so the thread ends inside the test rather than outliving it.
    """
    fifo = tmp_path / "never-written"
    os.mkfifo(fifo)
    monkeypatch.setattr(upload_read, "READ_TIMEOUT", 0.2)

    with pytest.raises(TimeoutError, match=r"did not finish within 0\.2s"):
        await read_upload(str(fifo), fifo)

    reader = next(
        t for t in threading.enumerate() if t.name == f"{READER_THREAD_PREFIX}{fifo.name}"
    )
    assert reader.daemon, "the reader thread would be joined at exit"
    assert reader.is_alive(), "the reader should still be parked in open()"

    os.close(os.open(fifo, os.O_WRONLY))
    assert poll_until_sync(lambda: not reader.is_alive(), deadline=5.0), "reader never ended"
