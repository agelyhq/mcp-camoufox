from __future__ import annotations

from camoufox_mcp.dom.actions import (
    file_input_selector,
    fill_field,
    resolve_center,
    scroll_into_view,
)
from camoufox_mcp.dom.snapshot import capture_snapshot
from camoufox_mcp.dom.uid import resolve_uid_or_raise

__all__ = [
    "capture_snapshot",
    "file_input_selector",
    "fill_field",
    "resolve_center",
    "resolve_uid_or_raise",
    "scroll_into_view",
]
