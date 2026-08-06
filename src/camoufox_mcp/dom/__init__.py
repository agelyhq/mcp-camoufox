"""The uid layer: one snapshot vocabulary, one element store, one clock.

Everything a tool may reach is re-exported here, and this is the only name a tool
imports: the seam ``tests/test_dom_layering.py`` pins is worth nothing if half the
surface is reached through submodule paths that the facade never mentions.

The converse holds too: a name nothing outside ``dom/`` imports is not part of the
layer's surface and does not belong here, however public it is inside it. Re-exporting
one advertises a boundary the module was never designed to be.
"""

from __future__ import annotations

from camoufox_mcp.dom.actions import MAX_UPLOAD_BYTES, fill_field, set_files
from camoufox_mcp.dom.capture import (
    DEFAULT_INTERACTIVE_ONLY,
    DEFAULT_MAX_NODES,
    capture_snapshot,
    find_elements,
)
from camoufox_mcp.dom.identity import (
    bind_selector,
    locate_many,
    locate_visible,
    resolve,
    scroll_uid,
)
from camoufox_mcp.dom.markup import MARKUP_MODES, read_markup
from camoufox_mcp.dom.page_protocol import ActionablePage, EvaluatablePage, RegistryPage
from camoufox_mcp.dom.reads import NAMED_PROPS, READABLE_PROPS, read_property
from camoufox_mcp.dom.registry import ElementRegistry
from camoufox_mcp.dom.scripting import evaluate_with_uids
from camoufox_mcp.dom.waiting import PollExpiredError, poll_until

__all__ = [
    "DEFAULT_INTERACTIVE_ONLY",
    "DEFAULT_MAX_NODES",
    "MARKUP_MODES",
    "MAX_UPLOAD_BYTES",
    "NAMED_PROPS",
    "READABLE_PROPS",
    "ActionablePage",
    "ElementRegistry",
    "EvaluatablePage",
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
    "read_markup",
    "read_property",
    "resolve",
    "scroll_uid",
    "set_files",
]
