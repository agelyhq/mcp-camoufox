"""The uid layer: one snapshot vocabulary, one element store, one clock.

Everything a tool may reach is re-exported here, and this is the only name a tool
imports: the seam ``tests/test_dom_layering.py`` pins is worth nothing if half the
surface is reached through submodule paths that the facade never mentions.
"""

from __future__ import annotations

from camoufox_mcp.dom.actions import MAX_UPLOAD_BYTES, fill_field, set_files
from camoufox_mcp.dom.capture import (
    DEFAULT_INTERACTIVE_ONLY,
    DEFAULT_MAX_NODES,
    capture_snapshot,
    find_elements,
)
from camoufox_mcp.dom.errors import raise_for
from camoufox_mcp.dom.identity import (
    bind_selector,
    locate_many,
    locate_visible,
    resolve,
    scroll_uid,
)
from camoufox_mcp.dom.page_protocol import (
    ActionablePage,
    EvaluatablePage,
    JsHandle,
    RegistryPage,
)
from camoufox_mcp.dom.reads import NAMED_PROPS, READABLE_PROPS, read_property
from camoufox_mcp.dom.registry import ElementRegistry
from camoufox_mcp.dom.scripting import evaluate_with_uids
from camoufox_mcp.dom.waiting import ACTION_DEADLINE, PollExpiredError, poll_until

__all__ = [
    "ACTION_DEADLINE",
    "DEFAULT_INTERACTIVE_ONLY",
    "DEFAULT_MAX_NODES",
    "MAX_UPLOAD_BYTES",
    "NAMED_PROPS",
    "READABLE_PROPS",
    "ActionablePage",
    "ElementRegistry",
    "EvaluatablePage",
    "JsHandle",
    "PollExpiredError",
    "RegistryPage",
    "bind_selector",
    "capture_snapshot",
    "evaluate_with_uids",
    "fill_field",
    "find_elements",
    "locate_many",
    "locate_visible",
    "poll_until",
    "raise_for",
    "read_property",
    "resolve",
    "scroll_uid",
    "set_files",
]
