from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import Client

PROFILE = "test"


def extract_uid(snapshot: str, label: str) -> str:
    """Find the UID for an element containing `label` in the snapshot text."""
    for line in snapshot.splitlines():
        if label.lower() in line.lower():
            match = re.search(r"e\d+", line)
            if match:
                return match.group()
    msg = f"No UID found for label '{label}' in snapshot"
    raise ValueError(msg)


def extract_first_reqid(listing: str) -> int:
    """Extract the first reqid from a network request listing.

    Each data line starts with the bracketed reqid:
        [1] GET 200 fetch http://...
    """
    for line in listing.splitlines():
        match = re.search(r"\[(\d+)\]", line)
        if match:
            return int(match.group(1))
    msg = "No reqid found in listing"
    raise ValueError(msg)


def tool_text(result: object) -> str:
    """Extract text from a CallToolResult (.data is the text string)."""
    return result.data


async def evaluate(client: Client, profile: str, script: str) -> str:
    """Run the ``evaluate`` tool for ``profile`` and return its text output."""
    return tool_text(await client.call_tool("evaluate", {"profile": profile, "script": script}))


async def text_content(client: Client, profile: str, element_id: str) -> str:
    """Return the ``textContent`` of ``#element_id`` on the active page."""
    return await evaluate(client, profile, f"document.getElementById({element_id!r}).textContent")


async def goto_and_find(client: Client, url: str, profile: str, label: str) -> str:
    """Navigate to ``url``, snapshot the page, and return the UID matching ``label``."""
    await client.call_tool("navigate", {"url": url, "profile": profile})
    snap = tool_text(await client.call_tool("snapshot", {"profile": profile}))
    return extract_uid(snap, label)
