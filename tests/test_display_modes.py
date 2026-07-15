from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from tests.helpers import tool_text

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

    monkeypatch.setenv("CAMOUFOX_HEADLESS", mode)
    monkeypatch.setenv("CAMOUFOX_AUTO_UPDATE", "false")
    monkeypatch.setenv("CAMOUFOX_DATA_DIR", str(data_dir))
    monkeypatch.delenv("CAMOUFOX_PROXY", raising=False)
    monkeypatch.delenv("CAMOUFOX_FINGERPRINT_OS", raising=False)
    monkeypatch.delenv("CAMOUFOX_VIEWPORT", raising=False)
    monkeypatch.delenv("CAMOUFOX_LOCALE", raising=False)

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.server import build_server

    server = build_server(ServerConfig.from_env())
    async with Client(server) as client:
        result = tool_text(
            await client.call_tool("navigate", {"profile": "display", "url": f"{flask_server}/"})
        )

    assert "Navigated to" in result, f"navigate failed in headless={mode!r}: {result}"
