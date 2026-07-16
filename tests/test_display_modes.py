from __future__ import annotations

import os
import re
import shutil
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from tests.helpers import isolate_camoufox_env, tool_text

if TYPE_CHECKING:
    from pathlib import Path

# Modes that can launch in a display-less test environment. Pure "false" (a real
# visible window) is deliberately excluded: it needs a working desktop GL stack and
# cannot be exercised headlessly — the deployed config uses "virtual" instead.
_HEADLESS_MODES = ["true", "virtual"]


@pytest.mark.parametrize("mode", _HEADLESS_MODES)
async def test_display_mode_launches(
    mode: str,
    data_dir: Path,
    flask_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server must actually launch a browser in each shipped headless mode.

    Regression guard: the suite otherwise runs only in "true", so a break in the
    virtual (Xvfb) launch path — the mode the deployed config uses — would slip
    through. This drives a real navigate end-to-end in each mode.
    """
    if mode == "virtual" and shutil.which("Xvfb") is None:
        pytest.skip("Xvfb is not installed; cannot exercise virtual display mode")

    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_HEADLESS=mode)

    from camoufox_mcp.bootstrap import build_server
    from camoufox_mcp.config import ServerConfig

    server = build_server(ServerConfig.from_env())
    async with Client(server) as client:
        result = tool_text(
            await client.call_tool("navigate", {"profile": "display", "url": f"{flask_server}/"})
        )

    assert "Navigated to" in result, f"navigate failed in headless={mode!r}: {result}"


async def test_navigate_headless_param_creates_virtual(
    data_dir: Path,
    flask_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-session headless='virtual' override wins over an env default of 'true'.

    Teeth: 'virtual' spawns Xvfb and repoints the process-global DISPLAY to it, while
    an invisible 'true' launch touches no display. With DISPLAY cleared and the env
    default set to 'true', a DISPLAY appearing after navigate proves the param — not
    the env — drove the launch into virtual mode.
    """
    if shutil.which("Xvfb") is None:
        pytest.skip("Xvfb is not installed; cannot exercise virtual display mode")

    isolate_camoufox_env(monkeypatch, data_dir)
    monkeypatch.delenv("DISPLAY", raising=False)

    from camoufox_mcp.bootstrap import build_server
    from camoufox_mcp.config import ServerConfig

    server = build_server(ServerConfig.from_env())
    async with Client(server) as client:
        result = tool_text(
            await client.call_tool(
                "navigate",
                {"profile": "vparam", "url": f"{flask_server}/", "headless": "virtual"},
            )
        )

    assert "Navigated to" in result, result
    display = os.environ.get("DISPLAY", "")
    assert re.fullmatch(r":\d+", display), f"virtual mode must set a DISPLAY, got {display!r}"
    assert int(display[1:]) >= 99


async def test_navigate_headless_invalid(
    data_dir: Path,
    flask_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown headless value is rejected before any browser launches."""
    isolate_camoufox_env(monkeypatch, data_dir)

    from camoufox_mcp.bootstrap import build_server
    from camoufox_mcp.config import ServerConfig

    server = build_server(ServerConfig.from_env())
    async with Client(server) as client:
        result = tool_text(
            await client.call_tool(
                "navigate",
                {"profile": "hbad", "url": f"{flask_server}/", "headless": "bogus"},
            )
        )

    assert "Error: ValueError:" in result
    assert "invalid headless" in result


async def test_navigate_headless_creation_only(
    data_dir: Path,
    flask_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """headless is creation-only: a later override on an active profile is ignored.

    The env default is 'true'; the second navigate asks for 'virtual' but the session
    already exists, so it is silently ignored (and no Xvfb is ever spawned — hence no
    Xvfb guard here). The 'options ignored' note must name headless.
    """
    isolate_camoufox_env(monkeypatch, data_dir)

    from camoufox_mcp.bootstrap import build_server
    from camoufox_mcp.config import ServerConfig

    server = build_server(ServerConfig.from_env())
    async with Client(server) as client:
        first = tool_text(
            await client.call_tool("navigate", {"profile": "hco", "url": f"{flask_server}/"})
        )
        assert "Navigated to" in first

        second = tool_text(
            await client.call_tool(
                "navigate",
                {"profile": "hco", "url": f"{flask_server}/click", "headless": "virtual"},
            )
        )

    assert "Navigated to" in second
    assert "options ignored" in second
    assert "headless" in second
