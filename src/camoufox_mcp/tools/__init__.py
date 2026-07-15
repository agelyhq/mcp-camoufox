from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

logger = logging.getLogger(__name__)


def register_all_tools(mcp: FastMCP, deps: ToolDeps) -> None:
    """Auto-discover every tool module in this package and register it.

    Each public module (name not starting with ``_``) must expose
    ``register(mcp, deps) -> None``. Discovery is dynamic so parallel authors can
    add tool files without touching a shared list.
    """
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        register = getattr(module, "register", None)
        if register is None:
            logger.warning("Tool module %s has no register(mcp, deps); skipping", module_info.name)
            continue
        register(mcp, deps)
