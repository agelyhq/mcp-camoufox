"""``upload_file``'s pipeline: a typed path to the ``File`` the page receives.

The steps are owned elsewhere and only ordered here: ``upload_path`` turns the text
into a path, ``upload_read`` asks the kernel and reads the bytes, ``upload_mime`` names
their type, and the ``setFiles`` page operation builds the ``File``. This module holds
the one rule that spans them, the size ceiling, and the confirmation line.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from camoufox_mcp.dom.errors import raise_for
from camoufox_mcp.dom.identity import element_call
from camoufox_mcp.dom.upload_mime import guess_mime
from camoufox_mcp.dom.upload_path import payload_name, resolve_upload_path
from camoufox_mcp.dom.upload_read import read_upload, stat_upload
from camoufox_mcp.dom.waiting import UPLOAD_TIMEOUT

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import RegistryPage

# The bytes cross the protocol base64-encoded, so a ceiling is needed where the
# local-path route had none.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def set_files(page: RegistryPage, uid: str, file_path: str) -> str:
    """Attach a local file to the file input a uid points at (or controls).

    The confirmation states the name, type and size the page's ``File`` was built
    with, so a wrong one is visible without a second call: those three are what a
    site's own accept check reads, and they are derived here, not typed by the caller.
    """
    path = resolve_upload_path(file_path)
    size = stat_upload(file_path, path).st_size
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"'{file_path}' is {size} bytes; upload_file accepts at most {MAX_UPLOAD_BYTES} bytes"
        )
    data = await read_upload(file_path, path)
    name = payload_name(path)
    mime = guess_mime(data, name)
    payload = {"name": name, "type": mime, "data": base64.b64encode(data).decode("ascii")}
    info = await element_call(page, "setFiles", uid, payload, timeout=UPLOAD_TIMEOUT)
    raise_for(info, uid, op="setFiles")
    return f"Uploaded {name} ({mime}, {len(data)} bytes) to {uid}"
