from __future__ import annotations

from camoufox_mcp.dom.actions import (
    clear_field,
    file_input_selector,
    fill_field,
    scroll_into_view,
)
from camoufox_mcp.dom.page_protocol import ActionablePage, EvaluatablePage
from camoufox_mcp.dom.snapshot import (
    get_clear_field_js,
    get_file_input_selector_js,
    get_resolve_uid_js,
    get_scroll_into_view_js,
    get_snapshot_js,
)
from camoufox_mcp.dom.uid import (
    resolve_center,
    resolve_uid,
    resolve_uid_or_raise,
    run_js_action,
    uid_selector,
    valid_uid,
)

__all__ = [
    "ActionablePage",
    "EvaluatablePage",
    "clear_field",
    "file_input_selector",
    "fill_field",
    "get_clear_field_js",
    "get_file_input_selector_js",
    "get_resolve_uid_js",
    "get_scroll_into_view_js",
    "get_snapshot_js",
    "resolve_center",
    "resolve_uid",
    "resolve_uid_or_raise",
    "run_js_action",
    "scroll_into_view",
    "uid_selector",
    "valid_uid",
]
