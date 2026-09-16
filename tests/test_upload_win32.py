"""The upload-path rules only Windows exercises, checked as the pure logic they are.

None of these has a public-surface path off Windows: the shapes a Windows user types
(``%USERPROFILE%``, ``file:///C:/``, a UNC share, the drive-relative ``C:foo`` and the
WSL mount that Explorer never produces), the ``\\\\?\\`` prefix Win32 needs past 260
characters, the cloud-placeholder refusal that reads a ``stat`` attribute only NTFS
carries, the trailing space and period Win32 drops from a file name, the length note a
not-found line gets and the sharing-violation reading of ``EACCES``. Each rule keys on
the path's flavour, never on ``os.name``, so a ``PureWindowsPath`` drives the Windows
branch here and no global is patched.
"""

from __future__ import annotations

import errno
import os
from pathlib import PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import pytest

from camoufox_mcp.dom.upload_path import (
    EXTENDED_PREFIX,
    MAX_PATH,
    payload_name,
    resolve_upload_path,
    win32_extended,
)
from camoufox_mcp.dom.upload_read import check_placeholder, read_upload, stat_upload

_LONG = "C:\\Users\\someone\\OneDrive - Company\\Desktop\\" + "campaign-" * 30 + "final.png"
# Two short of the ceiling: Explorer's "Copy as path" quotes push the TYPED string to
# 260 while the path itself stays under it.
_ALMOST = "C:\\" + "a" * (MAX_PATH - 2 - len("C:\\"))
_HOME = "C:\\Users\\someone"
_NOT_ABSOLUTE = "file_path must be an absolute path on this machine; got "
LOCK_HINT = "; the file may be open in another program: close it and retry"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ('"C:\\Users\\someone\\Desktop\\post.png"', "C:\\Users\\someone\\Desktop\\post.png"),
        ("C:/Users/someone/Desktop/post.png", "C:\\Users\\someone\\Desktop\\post.png"),
        ("%USERPROFILE%\\Pictures\\post.png", f"{_HOME}\\Pictures\\post.png"),
        ("~\\Pictures\\post.png", f"{_HOME}\\Pictures\\post.png"),
        ("file:///C:/Users/someone/a%20b.png", "C:\\Users\\someone\\a b.png"),
        ("\\\\server\\share\\post.png", "\\\\server\\share\\post.png"),
        (_LONG, EXTENDED_PREFIX + _LONG),
    ],
    ids=["copy-as-path", "forward-slashes", "userprofile", "tilde", "file-uri", "unc", "long"],
)
def test_windows_shapes_resolve_on_the_windows_flavour(
    typed: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every shape a Windows user pastes lands on the drive it names, with the
    ``\\\\?\\`` prefix added past ``MAX_PATH`` and nowhere else."""
    monkeypatch.setenv("USERPROFILE", _HOME)
    resolved = resolve_upload_path(typed, flavour=PureWindowsPath)
    assert isinstance(resolved, PureWindowsPath)
    assert str(resolved) == expected


@pytest.mark.parametrize(
    ("typed", "tail"),
    [
        ("C:post.png", ""),
        ("\\Users\\someone\\post.png", ""),
        ("/mnt/c/Users/someone/post.png", "; that is a WSL path: on Windows use C:\\..."),
        ("%USERPROFILE%\\post.png", ""),
    ],
    ids=["drive-relative", "rooted-no-drive", "wsl-mount", "unset-variable"],
)
def test_relative_windows_shapes_are_refused(
    typed: str, tail: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``C:foo`` and ``\\foo`` are relative on Windows, ``/mnt/c/`` is a WSL path and
    says so, and a variable Windows would leave unexpanded stays unexpanded."""
    monkeypatch.delenv("USERPROFILE", raising=False)
    with pytest.raises(ValueError, match="absolute path") as refused:
        resolve_upload_path(typed, flavour=PureWindowsPath)
    message = str(refused.value)
    assert message.startswith(f"{_NOT_ABSOLUTE}'{typed}' (server working directory: "), message
    assert message.endswith(f"{os.getcwd()}){tail}"), message


def test_a_posix_shape_refused_on_windows_shows_what_it_expanded_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``$HOME/...`` typed on Windows is refused with the text it became, so the
    caller sees the expansion happened and the drive is what is missing."""
    monkeypatch.setenv("HOME", "/home/someone")
    with pytest.raises(ValueError, match="absolute path") as refused:
        resolve_upload_path("$HOME/post.png", flavour=PureWindowsPath)
    assert str(refused.value).startswith(
        f"{_NOT_ABSOLUTE}'$HOME/post.png' (expanded to '/home/someone/post.png') "
    ), str(refused.value)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("C:\\Users\\someone\\Desktop\\post.png", "C:\\Users\\someone\\Desktop\\post.png"),
        (_LONG, EXTENDED_PREFIX + _LONG),
        (_LONG.replace("\\", "/"), EXTENDED_PREFIX + _LONG),
        (_LONG.replace("Desktop\\", "Desktop\\..\\Desktop\\"), EXTENDED_PREFIX + _LONG),
        (EXTENDED_PREFIX + _LONG, EXTENDED_PREFIX + _LONG),
        ("\\\\server\\share\\" + _LONG[3:], EXTENDED_PREFIX + "UNC\\server\\share\\" + _LONG[3:]),
        (_ALMOST.replace("C:\\", "C:\\..\\..\\..\\"), _ALMOST.replace("C:\\", "C:\\..\\..\\..\\")),
    ],
    ids=["short", "long", "forward-slashes", "dot-dot", "already-prefixed", "unc", "dot-dot-short"],
)
def test_win32_extended_form(typed: str, expected: str) -> None:
    """The prefix is applied only past ``MAX_PATH`` measured after ``normpath``, and
    keeps the drive and the name intact: a ``..`` chain that types past the ceiling but
    normalises under it is left for Win32 to open as typed."""
    extended = win32_extended(PureWindowsPath(typed))
    assert str(extended) == expected
    assert extended.name == PureWindowsPath(typed).name
    assert extended.drive, extended


def test_placeholder_attribute_is_refused_before_the_read() -> None:
    """The recall-on-data-access and offline bits each refuse; a plain file passes."""
    for bits in (0x400000, 0x1000, 0x400020):
        with pytest.raises(ValueError, match="OneDrive/cloud placeholder"):
            check_placeholder(SimpleNamespace(st_file_attributes=bits), "C:\\x.png")  # type: ignore[arg-type]
    check_placeholder(SimpleNamespace(st_file_attributes=0x20), "C:\\x.png")  # type: ignore[arg-type]
    check_placeholder(os.stat(__file__), __file__)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (PureWindowsPath("C:\\x\\post.png "), "post.png"),
        (PureWindowsPath("C:\\x\\post.png."), "post.png"),
        (PureWindowsPath("C:\\x\\post.png"), "post.png"),
        (PureWindowsPath(EXTENDED_PREFIX + "C:\\x\\post.png "), "post.png "),
        (PurePosixPath("/x/post.png "), "post.png "),
    ],
    ids=["trailing-space", "trailing-period", "plain", "extended-keeps-it", "posix-keeps-it"],
)
def test_payload_name_applies_the_win32_trailing_rule_lexically(
    path: PureWindowsPath | PurePosixPath, expected: str
) -> None:
    """What Win32 opened is the typed name without its trailing spaces and periods,
    except under the ``\\\\?\\`` prefix, which switches that stripping off; the rule
    is lexical, so a symlink is never resolved to its target's name."""
    assert payload_name(path) == expected


def test_length_note_measures_the_resolved_path() -> None:
    """The note reads the path ``stat`` was asked about, prefix excluded, and never
    the typed string: quotes that push a 258-character path to 260 typed characters
    are not a MAX_PATH problem, and a path past it says it was tried in the long form."""
    with pytest.raises(ValueError, match="cannot read") as refused:
        stat_upload(f'"{_LONG}"', win32_extended(PureWindowsPath(_LONG)))
    assert str(refused.value).endswith(
        f" (checked '{EXTENDED_PREFIX}{_LONG}'); the path is {len(_LONG)} characters, "
        f"past Win32's {MAX_PATH} limit, tried in the \\\\?\\ form"
    ), str(refused.value)

    with pytest.raises(ValueError, match="cannot read") as refused:
        stat_upload(f'"{_ALMOST}"', win32_extended(PureWindowsPath(_ALMOST)))
    assert "characters" not in str(refused.value), str(refused.value)
    assert str(refused.value).endswith(f" (checked '{_ALMOST}')"), str(refused.value)


def _failing_read(
    flavour: type[PureWindowsPath | PurePosixPath], error: OSError
) -> PureWindowsPath | PurePosixPath:
    """A pure path whose ``read_bytes`` raises ``error``: the kernel's answer, staged."""

    class Unreadable(flavour):  # type: ignore[valid-type,misc]
        def read_bytes(self) -> bytes:
            raise error

    return Unreadable("C:\\x\\locked.png" if flavour is PureWindowsPath else "/x/locked.png")


async def test_eacces_on_a_windows_path_reads_as_a_sharing_violation() -> None:
    """``EACCES`` after a passing ``stat`` is what a file open elsewhere looks like on
    Windows, so the Windows path gets the hint and the POSIX one, same errno, does not."""
    denied = PermissionError(errno.EACCES, "Permission denied")
    with pytest.raises(ValueError) as windows:
        await read_upload("C:\\x\\locked.png", _failing_read(PureWindowsPath, denied))
    assert str(windows.value) == (
        f"cannot read 'C:\\x\\locked.png': Permission denied (errno {errno.EACCES}){LOCK_HINT}"
    )

    with pytest.raises(ValueError) as posix:
        await read_upload("/x/locked.png", _failing_read(PurePosixPath, denied))
    assert str(posix.value) == (
        f"cannot read '/x/locked.png': Permission denied (errno {errno.EACCES})"
    )


async def test_a_winerror_is_named_next_to_the_errno() -> None:
    """The Win32 code rides along when the kernel gave one, and another errno gets no
    lock hint: the hint is about ``EACCES`` alone."""
    invalid = OSError(
        errno.EINVAL, "The filename, directory name, or volume label syntax is incorrect"
    )
    invalid.winerror = 123  # type: ignore[attr-defined]
    with pytest.raises(ValueError) as refused:
        await read_upload("C:\\x\\locked.png", _failing_read(PureWindowsPath, invalid))
    assert str(refused.value) == (
        "cannot read 'C:\\x\\locked.png': The filename, directory name, or volume label "
        f"syntax is incorrect (errno {errno.EINVAL}, winerror 123)"
    )
