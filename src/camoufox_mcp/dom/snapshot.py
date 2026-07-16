from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import EvaluatablePage

_JS_DIR = Path(__file__).resolve().parent / "js"

_JS_CACHE: dict[str, str] = {}


def _load_js(name: str) -> str:
    if name not in _JS_CACHE:
        _JS_CACHE[name] = (_JS_DIR / name).read_text(encoding="utf-8")
    return _JS_CACHE[name]


def get_snapshot_js() -> str:
    return _load_js("snapshot.js")


async def capture_snapshot(
    page: EvaluatablePage, max_nodes: int = 1500, interactive_only: bool = False
) -> str:
    """Snapshot the active page as an indented uid tree, capped at ``max_nodes``.

    The DOM walk assigns ``eN`` uids in pre-order, so the kept prefix keeps the
    exact uids it would have in an uncapped snapshot. When more nodes exist than
    ``max_nodes``, whole trailing nodes are dropped (never a partial line) and a
    truncation note is appended. ``interactive_only`` drops structural leaves with
    no interactive descendant, keeping every interactive element plus the ancestor
    chain that gives it context. ``max_nodes <= 0`` disables the cap.
    """
    opts = {"maxNodes": max_nodes, "interactiveOnly": interactive_only}
    result = await page.evaluate(f"({get_snapshot_js()})({json.dumps(opts)})")
    if not isinstance(result, dict):
        return str(result)

    tree = str(result.get("tree", ""))
    if result.get("truncated"):
        overflow = int(result.get("totalNodes", 0)) - int(result.get("shownNodes", 0))
        tree += (
            f"\n[truncated: {overflow} more nodes — raise max_nodes or use interactive_only=true]"
        )
    return tree


def get_resolve_uid_js() -> str:
    return _load_js("resolve_uid.js")


def get_clear_field_js() -> str:
    return _load_js("clear_field.js")


def get_scroll_into_view_js() -> str:
    return _load_js("scroll_into_view.js")


def get_file_input_selector_js() -> str:
    return _load_js("file_input_selector.js")
