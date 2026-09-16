"""The ``type`` of the ``File`` the page receives, read from the bytes before the name.

``mimetypes`` on Windows loads every ``HKCR\\.ext`` "Content Type" value over its own
table, and a third-party installer that wrote ``image/pjpeg`` or nothing there makes a
sound photo reach the site as the wrong type. The magic bytes of the handful of formats
this tool exists for are not the registry's to override, so they are read first; the
name is only consulted for a format not sniffed here.
"""

from __future__ import annotations

import mimetypes

FALLBACK_MIME = "application/octet-stream"

# Prefix -> type, longest prefixes first so a match is never a shorter accident.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
_RIFF = b"RIFF"
_WEBP = b"WEBP"
_WEBP_TAG_AT = 8


def guess_mime(data: bytes, name: str) -> str:
    """The sniffed type of ``data``, then ``mimetypes``'s answer for ``name``, then the
    octet-stream fallback."""
    head = data[:16]
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    if head.startswith(_RIFF) and head[_WEBP_TAG_AT : _WEBP_TAG_AT + len(_WEBP)] == _WEBP:
        return "image/webp"
    return mimetypes.guess_type(name)[0] or FALLBACK_MIME
