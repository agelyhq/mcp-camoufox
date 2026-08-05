"""Shared vocabulary of the suite: env isolation, tool calls and the contract strings.

Anything that polls a condition lives in :mod:`tests.waits`; anything that stands in
for a page or a handle lives in :mod:`tests.fakes`.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client, FastMCP
    from fastmcp.client.client import CallToolResult

PROFILE = "test"

# TEST_FLASK_PORT lets parallel pytest invocations avoid binding the same port. Read
# here so the conftest fixture and a standalone ``python -m tests.server`` run agree.
FLASK_PORT = int(os.environ.get("TEST_FLASK_PORT", "5123"))

# The headers an observed action appends before its snapshot or its text block. They
# are a contract with the caller, so every module asserting on one reads it from here.
OBSERVATION_SNAPSHOT_MARK = "--- observation (snapshot) ---"
OBSERVATION_TEXT_MARK = "--- observation (text) ---"

# The mandated stale-uid string, and the way the @tool wrapper renders it. Both are
# templated from one source so a change to either cannot pass half the suite.
STALE_UID = "unknown or stale uid '{uid}'; take a new snapshot"
RENDERED_STALE_UID = f"Error: ValueError: {STALE_UID}"

# A display number that cannot exist on the runner: Firefox refuses to start on it,
# which is what gives every "the launch never falls back to the ambient DISPLAY"
# assertion its teeth.
ABSENT_DISPLAY = ":424"

# Grows the page body innerText past the 4000-char observe=text cap.
BIG_TEXT_JS = (
    "document.body.insertAdjacentHTML('beforeend', '<p>' + 'x'.repeat(5000) + '</p>'); 'ok'"
)

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


def server_for(monkeypatch: pytest.MonkeyPatch, data_dir: Path, **env: str) -> FastMCP:
    """An in-process server bound to an isolated config, with ``env`` applied first.

    ``ServerConfig.from_env`` reads the environment when it is called, so the imports
    stay at module scope and only the read is ordered after ``isolate_camoufox_env``.
    """
    isolate_camoufox_env(monkeypatch, data_dir, **env)

    from camoufox_mcp.bootstrap import build_server
    from camoufox_mcp.config import ServerConfig

    return build_server(ServerConfig.from_env())


def extract_uid(snapshot: str, label: str) -> str:
    """Find the UID for an element containing `label` in the snapshot text."""
    for line in snapshot.splitlines():
        if label.lower() in line.lower():
            match = re.search(r"e\d+", line)
            if match:
                return match.group()
    msg = f"No UID found for label '{label}' in snapshot"
    raise ValueError(msg)


def uids(text: str) -> list[str]:
    """Every uid the rendered text names, in the order it rendered them."""
    return re.findall(r"\be\d+\b", text)


def _lines_with(text: str, needle: str) -> list[str]:
    return [line for line in text.splitlines() if needle in line]


def line_with(text: str, needle: str) -> str:
    """The one line holding ``needle``, asserting there is exactly one."""
    found = _lines_with(text, needle)
    assert len(found) == 1, f"expected exactly 1 line holding {needle!r}, got {found}"
    return found[0]


def tool_text(result: CallToolResult) -> str:
    """Extract text from a CallToolResult (.data is the text string)."""
    return result.data


async def evaluate(client: Client, profile: str, script: str) -> str:
    """Run the ``evaluate`` tool for ``profile`` and return its text output."""
    return tool_text(await client.call_tool("evaluate", {"profile": profile, "script": script}))


async def text_content(client: Client, profile: str, element_id: str) -> str:
    """Return the ``textContent`` of ``#element_id`` on the active page."""
    return await evaluate(client, profile, f"document.getElementById({element_id!r}).textContent")


async def open_page(client: Client, url: str, profile: str = PROFILE) -> None:
    """Navigate ``profile``'s active tab to ``url``."""
    await client.call_tool("navigate", {"url": url, "profile": profile})


async def snapshot_text(client: Client, profile: str = PROFILE, **kwargs: object) -> str:
    """The rendered snapshot of ``profile``'s active tab."""
    return tool_text(await client.call_tool("snapshot", {"profile": profile, **kwargs}))


async def open_and_snapshot(client: Client, url: str, profile: str = PROFILE) -> str:
    """Navigate to ``url`` and return the snapshot of what landed."""
    await open_page(client, url, profile)
    return await snapshot_text(client, profile)


async def goto_and_find(client: Client, url: str, profile: str, label: str) -> str:
    """Navigate to ``url``, snapshot the page, and return the UID matching ``label``."""
    return extract_uid(await open_and_snapshot(client, url, profile), label)


async def call_within(client: Client, tool: str, args: dict[str, object], budget: float) -> str:
    """Call ``tool`` with a guardrail on the clock instead of a stopwatch on it.

    ``assert elapsed < k`` around a call makes the runner's load part of the verdict:
    a correct implementation on a busy machine then reads exactly like a regression
    that reinstated an unbounded wait. The bound belongs here, where expiry fails
    loudly and the verdict stays the returned text.
    """
    try:
        result = await asyncio.wait_for(client.call_tool(tool, args), budget)
    except TimeoutError:
        pytest.fail(f"{tool} did not answer within its {budget:g}s guardrail")
    return tool_text(result)
