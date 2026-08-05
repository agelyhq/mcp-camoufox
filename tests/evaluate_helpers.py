"""Calls shared by the two ``evaluate`` suites: the behaviour one and the caps one."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, extract_uid, open_and_snapshot, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def uids_for_labels(client: Client, flask_server: str, *labels: str) -> list[str]:
    """Open the click fixture and return the uid of each named element."""
    snap = await open_and_snapshot(client, f"{flask_server}/click")
    return [extract_uid(snap, label) for label in labels]


async def evaluate_uids(client: Client, script: str, uids: list[str]) -> str:
    """Run ``script`` against the elements ``uids`` names."""
    return tool_text(
        await client.call_tool("evaluate", {"profile": PROFILE, "script": script, "uids": uids})
    )


async def capped(client: Client, script: str, **caps: int) -> str:
    """Run ``script`` with explicit output caps (``max_chars`` / ``max_items``)."""
    return tool_text(
        await client.call_tool("evaluate", {"profile": PROFILE, "script": script, **caps})
    )
