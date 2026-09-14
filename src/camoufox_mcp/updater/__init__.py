"""Throttled, non-blocking, fail-open auto-update of the Camoufox build and GeoIP data.

The parent side (:mod:`.startup`, :mod:`.builds`) reads disk and writes one config key;
every fetch runs in a child process (:mod:`.child` spawns :mod:`.fetch`), because this
process never assigns ``sys.stdout`` or ``sys.stderr``.
"""

from __future__ import annotations

from camoufox_mcp.updater.builds import binary_present, installed_build
from camoufox_mcp.updater.child import fetch_in_child
from camoufox_mcp.updater.errors import BrowserSetupError, FetchError
from camoufox_mcp.updater.startup import (
    STAMP_NAME,
    ensure_browser_present,
    schedule_refresh,
    write_update_stamp,
)

__all__ = [
    "STAMP_NAME",
    "BrowserSetupError",
    "FetchError",
    "binary_present",
    "ensure_browser_present",
    "fetch_in_child",
    "installed_build",
    "schedule_refresh",
    "write_update_stamp",
]
