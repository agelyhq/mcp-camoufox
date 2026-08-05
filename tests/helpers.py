from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastmcp import Client

PROFILE = "test"

# Optional per-session CAMOUFOX_* vars an ambient environment might set; cleared so a
# test's config is derived only from the values isolate_camoufox_env sets explicitly.
_OPTIONAL_ENV_VARS = (
    "CAMOUFOX_PROXY",
    "CAMOUFOX_FINGERPRINT_OS",
    "CAMOUFOX_VIEWPORT",
    "CAMOUFOX_LOCALE",
)


def isolate_camoufox_env(monkeypatch: pytest.MonkeyPatch, data_dir: Path, **overrides: str) -> None:
    """Point config at an isolated ``data_dir`` and clear inherited CAMOUFOX_* vars.

    Applies auto_update=false plus the data dir, then any ``overrides`` (full env var
    names, e.g. ``CAMOUFOX_HEADLESS="virtual"``), and finally deletes the optional
    per-session vars so the host environment never leaks.

    ``CAMOUFOX_HEADLESS`` is the one inherited var kept on purpose: it defaults to
    ``"true"`` so a bare run is deterministic and display-less, but an ambient value is
    honoured so the whole suite can be run under ``CAMOUFOX_HEADLESS=virtual`` (the
    recommended invisible Linux mode). Hard-setting it made that run a no-op that looked
    like coverage. A test whose assertion depends on a specific mode must pass it as an
    override rather than rely on the default.
    """
    env = {
        "CAMOUFOX_HEADLESS": os.environ.get("CAMOUFOX_HEADLESS") or "true",
        "CAMOUFOX_AUTO_UPDATE": "false",
        "CAMOUFOX_DATA_DIR": str(data_dir),
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for var in _OPTIONAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


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
