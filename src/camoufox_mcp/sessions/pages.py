from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from camoufox_mcp.sessions.page import Page


@dataclass(frozen=True)
class PageInfo:
    """Public view of a single tab for listing purposes."""

    index: int
    page: Page
    is_active: bool
