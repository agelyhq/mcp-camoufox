"""The disk half of ``upload_file``: what the caller typed, what the page received.

Every shape a Windows user pastes and a Linux user never does has a POSIX equivalent
driven here through the real tool and the local echo server: quotes, padding, a
``file:`` URI, ``~`` and ``$VAR``. The page's ``File`` name, type and size are read back
from what the server parsed out of the multipart body, so the success line is proved
against the wire and not against itself.

What happens once the path is resolved, a missing file, a folder, a read that fails or
never returns, is in :mod:`tests.test_upload_read`; the rules only Windows exercises
are in :mod:`tests.test_upload_win32`.
"""

from __future__ import annotations

import mimetypes
import os
from typing import TYPE_CHECKING

from tests.upload_helpers import TEXT, assert_attached, input_uid, upload

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastmcp import Client

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 24


async def test_quoted_path_from_copy_as_path(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """Explorer's "Copy as path" wraps in double quotes; the quotes are not a file name."""
    uid = await input_uid(client, flask_server)
    file = tmp_path / "quoted.txt"
    file.write_bytes(TEXT)

    await assert_attached(
        client, uid, f'"{file}"', name="quoted.txt", size=len(TEXT), mime="text/plain"
    )


async def test_single_quoted_path(client: Client, tmp_path: Path, flask_server: str) -> None:
    """A shell-style single-quoted path is unwrapped the same way."""
    uid = await input_uid(client, flask_server)
    file = tmp_path / "single.txt"
    file.write_bytes(TEXT)

    await assert_attached(
        client, uid, f"'{file}'", name="single.txt", size=len(TEXT), mime="text/plain"
    )


async def test_padded_path(client: Client, tmp_path: Path, flask_server: str) -> None:
    """A path pasted with surrounding whitespace names the file, not a file with spaces."""
    uid = await input_uid(client, flask_server)
    file = tmp_path / "padded.txt"
    file.write_bytes(TEXT)

    await assert_attached(
        client, uid, f"  {file} \n", name="padded.txt", size=len(TEXT), mime="text/plain"
    )


async def test_file_uri(client: Client, tmp_path: Path, flask_server: str) -> None:
    """A ``file:`` URI, the shape a browser's address bar hands over."""
    uid = await input_uid(client, flask_server)
    file = tmp_path / "from uri.txt"
    file.write_bytes(TEXT)

    await assert_attached(
        client, uid, file.as_uri(), name="from uri.txt", size=len(TEXT), mime="text/plain"
    )


async def test_tilde_expands_to_home(
    client: Client, tmp_path: Path, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = await input_uid(client, flask_server)
    monkeypatch.setenv("HOME", str(tmp_path))
    file = tmp_path / "home.txt"
    file.write_bytes(TEXT)

    await assert_attached(
        client, uid, "~/home.txt", name="home.txt", size=len(TEXT), mime="text/plain"
    )


async def test_environment_variable_expands(
    client: Client, tmp_path: Path, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``$VAR`` here, ``%VAR%`` on Windows: both go through the same expansion."""
    uid = await input_uid(client, flask_server)
    monkeypatch.setenv("UPLOAD_TEST_DIR", str(tmp_path))
    file = tmp_path / "var.txt"
    file.write_bytes(TEXT)

    await assert_attached(
        client, uid, "$UPLOAD_TEST_DIR/var.txt", name="var.txt", size=len(TEXT), mime="text/plain"
    )


async def test_relative_path_names_the_working_directory(
    client: Client, tmp_path: Path, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare name is refused even when it WOULD resolve: the cwd is the client's choice,
    and the message names it so the caller learns what an absolute path must start with."""
    uid = await input_uid(client, flask_server)
    (tmp_path / "relative.txt").write_bytes(TEXT)
    monkeypatch.chdir(tmp_path)

    result = await upload(client, uid, "relative.txt")
    assert result == (
        "Error: ValueError: file_path must be an absolute path on this machine; "
        f"got 'relative.txt' (server working directory: {os.getcwd()})"
    ), result


async def test_symlink_keeps_its_own_name(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """The page's ``File`` is named after the path the caller chose, not the link's target."""
    uid = await input_uid(client, flask_server)
    target = tmp_path / "IMG_1234.txt"
    target.write_bytes(TEXT)
    link = tmp_path / "post.txt"
    link.symlink_to(target)

    await assert_attached(
        client, uid, str(link), name="post.txt", size=len(TEXT), mime="text/plain"
    )


async def test_type_comes_from_the_bytes_not_the_extension(
    client: Client, tmp_path: Path, flask_server: str
) -> None:
    """A PNG renamed ``.dat`` still reaches the page as ``image/png``."""
    uid = await input_uid(client, flask_server)
    file = tmp_path / "renamed.dat"
    file.write_bytes(PNG_BYTES)

    await assert_attached(
        client, uid, str(file), name="renamed.dat", size=len(PNG_BYTES), mime="image/png"
    )


async def test_type_survives_a_corrupted_mimetypes_table(
    client: Client, tmp_path: Path, flask_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the Windows registry does to ``mimetypes``, done through its public table."""
    uid = await input_uid(client, flask_server)
    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map, ".jpeg", "image/pjpeg")
    assert mimetypes.guess_type("photo.jpeg")[0] == "image/pjpeg"
    file = tmp_path / "photo.jpeg"
    file.write_bytes(JPEG_BYTES)

    await assert_attached(
        client, uid, str(file), name="photo.jpeg", size=len(JPEG_BYTES), mime="image/jpeg"
    )
