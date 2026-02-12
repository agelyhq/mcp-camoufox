from __future__ import annotations

import re


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

    The listing format has reqid as the first number on data lines:
        1  GET      200  fetch      http://...
    """
    for line in listing.splitlines():
        stripped = line.strip()
        if stripped and stripped[0].isdigit():
            match = re.match(r"(\d+)", stripped)
            if match:
                return int(match.group(1))
    msg = "No reqid found in listing"
    raise ValueError(msg)


def tool_text(result: object) -> str:
    """Extract text from a CallToolResult (.data is the text string)."""
    return result.data
