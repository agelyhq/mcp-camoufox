from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps


def register_all_tools(mcp: FastMCP, deps: ToolDeps) -> None:
    """Auto-discover every tool module in this package and register it.

    Each public module (name not starting with ``_``) must expose
    ``register(mcp, deps) -> None``. Discovery is dynamic so parallel authors can
    add tool files without touching a shared list.

    A module without that function is a composition-time defect, and it fails the
    server start rather than being skipped: warning and continuing would silently
    ship a smaller tool surface than the one the product documents, and discovery
    runs exactly once, where a hard failure is cheap and visible.
    """
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        register = getattr(module, "register", None)
        if register is None:
            raise RuntimeError(f"tool module '{module_info.name}' has no register(mcp, deps)")
        register(mcp, deps)
