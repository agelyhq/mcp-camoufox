"""What the caller typed, as the path the kernel will be asked about.

Pure text: nothing here touches the disk, which is :mod:`camoufox_mcp.dom.upload_read`'s
half. The caller's raw string is what every message echoes, because it is the thing the
caller can correct; the resolved path is named too whenever it differs from what was
typed, so a ``~``, ``%VAR%`` or ``file:`` shape that expanded to the wrong place shows
where it went.

Every shape a Windows user produces and a Linux user never does is accepted here:
Explorer's "Copy as path" wraps in double quotes, ``%USERPROFILE%`` and ``~`` name the
home, ``file:///C:/...`` comes from a browser, and a path of 260 or more characters is
refused by Win32 unless it carries the ``\\\\?\\`` prefix. A relative path is refused
outright: the working directory of this server is whatever the client chose, and a
silent guess at it is a file the caller never named.

Every Windows rule keys on the path's flavour, never on ``os.name``: ``resolve_upload_path``
takes the flavour as a public keyword, defaulting to this platform's, so the Windows
branch is driven on any machine with a ``PureWindowsPath`` and no global is patched.

The ``%VAR%``/``$VAR`` and ``~`` expansions read the environment on purpose, the one
sanctioned read outside ``config.py``: they expand caller-typed input against the
environment of the process doing the reading, and are no server configuration.
"""

from __future__ import annotations

import ntpath
import nturl2path
import os
import posixpath
import urllib.parse
from pathlib import Path, PurePath, PureWindowsPath

# Win32's classic ceiling on a path, prefix and terminator included. At or past it a
# plain path fails ``stat`` with ENOENT on a file Explorer opens fine, unless the
# ``LongPathsEnabled`` policy is on, which it is not by default.
MAX_PATH = 260
EXTENDED_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\"

# Win32 strips these from the last path component before NTFS sees it, so the name the
# kernel opened is the typed one without them. Not under the ``\\\\?\\`` prefix, which
# switches that normalisation off along with the length ceiling.
_WIN32_TRAILING = " ."

_QUOTES = ('"', "'")
_WSL_MOUNT_LEN = len("/mnt/c/")


def resolve_upload_path[P: PurePath](raw: str, *, flavour: type[P] = Path) -> P:
    """The absolute path ``raw`` names on this machine, or ``ValueError`` saying why not.

    In order: surrounding whitespace, one pair of matching quotes, a ``file:`` URI,
    ``%VAR%``/``$VAR``, then ``~``. Nothing here touches the disk. ``flavour`` picks the
    rules: a Windows flavour reads ``file:///C:/`` as a drive, ``%VAR%`` as a variable
    and ``USERPROFILE`` as the home, and refuses ``C:foo`` and ``/mnt/c/...`` as the
    relative shapes they are there.
    """
    windows = issubclass(flavour, PureWindowsPath)
    ospath = ntpath if windows else posixpath
    text = _from_file_uri(_unquoted(raw.strip()), windows=windows)
    expanded = ospath.expanduser(ospath.expandvars(text))
    path = flavour(expanded)
    if not path.is_absolute():
        note = "" if expanded == raw.strip() else f" (expanded to '{expanded}')"
        raise ValueError(
            f"file_path must be an absolute path on this machine; got '{raw}'{note} "
            f"(server working directory: {os.getcwd()}){_wsl_hint(text, windows=windows)}"
        )
    if isinstance(path, PureWindowsPath):
        return flavour(win32_extended(path))
    return path


def win32_extended(path: PureWindowsPath) -> PureWindowsPath:
    """``path`` in the ``\\\\?\\`` form when Win32 would refuse it for length, else as is.

    ``normpath`` and never ``abspath``: the prefix switches Win32 normalisation off, so
    forward slashes, ``.`` and ``..`` must be resolved before it is applied, and the
    length is measured on that resolved text, the one ``upload_read`` reports in its
    length note. A UNC path takes the ``\\\\?\\UNC\\server\\share`` spelling.
    """
    text = str(path)
    if text.startswith(EXTENDED_PREFIX):
        return path
    normalised = ntpath.normpath(text)
    if len(normalised) < MAX_PATH:
        return path
    if normalised.startswith(_UNC_PREFIX):
        return type(path)(f"{EXTENDED_PREFIX}UNC{normalised[1:]}")
    return type(path)(f"{EXTENDED_PREFIX}{normalised}")


def payload_name(path: PurePath) -> str:
    """The name the page's ``File`` carries: the one on disk, not the one typed.

    Win32 strips trailing spaces and periods from the last component before NTFS sees
    it, so ``post.png `` opens ``post.png``, the spelling a site's ``.png$`` check must
    see. The same rule is applied lexically here, never by asking the kernel: a
    ``resolve`` would follow a symlink or junction and name its target instead of the
    file the caller chose.
    """
    if not isinstance(path, PureWindowsPath) or str(path).startswith(EXTENDED_PREFIX):
        return path.name
    return path.name.rstrip(_WIN32_TRAILING)


def _unquoted(text: str) -> str:
    """One matching pair of surrounding quotes removed: Explorer's "Copy as path"."""
    if len(text) >= 2 and text[0] in _QUOTES and text[-1] == text[0]:
        return text[1:-1]
    return text


def _from_file_uri(text: str, *, windows: bool) -> str:
    """A ``file:`` URI as the path it names; anything else untouched.

    The Windows decoder is what turns ``file:///C:/x`` into ``C:\\x``; the POSIX one
    only undoes the percent-escapes, which is all ``url2pathname`` does there.
    """
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() != "file":
        return text
    host = "" if parts.netloc.lower() in ("", "localhost") else f"//{parts.netloc}"
    decode = nturl2path.url2pathname if windows else urllib.parse.unquote
    return host + decode(parts.path)


def _wsl_hint(text: str, *, windows: bool) -> str:
    """The one relative-looking shape that is a real path on the wrong side of WSL."""
    if not windows:
        return ""
    is_mount = (
        len(text) >= _WSL_MOUNT_LEN and text[:5] == "/mnt/" and text[5].isalpha() and text[6] == "/"
    )
    return f"; that is a WSL path: on Windows use {text[5].upper()}:\\..." if is_mount else ""
