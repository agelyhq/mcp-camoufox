from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client

from tests.helpers import isolate_camoufox_env, tool_text

if TYPE_CHECKING:
    from pathlib import Path

# Modes that can launch in a display-less test environment. Pure "false" (a real
# visible window) is deliberately excluded: it needs a working desktop GL stack and
# cannot be exercised headlessly, so the deployed config uses "virtual" instead.
_HEADLESS_MODES = ["true", "virtual"]

# A display number that cannot exist on the runner. Firefox refuses to start on it,
# which is what gives the isolation test its teeth.
_ABSENT_DISPLAY = ":424"


def test_isolation_helper_honours_an_ambient_mode(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole suite must be runnable under CAMOUFOX_HEADLESS=virtual.

    The isolation helper used to hard-set 'true', so an operator running the suite in
    virtual mode (the recommended invisible Linux mode) exercised the 'true' path in
    every fixture-driven test and believed the opposite: only the 2 tests that pass the
    mode themselves ever reached Xvfb. Three cases in one, because all 3 have to hold
    together: with nothing ambient the default stays 'true' so a bare run is
    deterministic and display-less, an ambient value is honoured, and an explicit
    override still beats both so a test can pin the mode its assertion depends on.
    """
    from camoufox_mcp.config import ServerConfig

    monkeypatch.delenv("CAMOUFOX_HEADLESS", raising=False)
    isolate_camoufox_env(monkeypatch, data_dir)
    assert ServerConfig.from_env().headless is True

    monkeypatch.setenv("CAMOUFOX_HEADLESS", "virtual")
    isolate_camoufox_env(monkeypatch, data_dir)
    assert ServerConfig.from_env().headless == "virtual"

    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_HEADLESS="true")
    assert ServerConfig.from_env().headless is True


@pytest.mark.parametrize("mode", _HEADLESS_MODES)
async def test_display_mode_launches(
    mode: str,
    data_dir: Path,
    flask_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server must actually launch a browser in each shipped headless mode.

    Regression guard: the suite otherwise runs only in "true", so a break in the
    virtual (Xvfb) launch path, the mode the deployed config uses, would slip
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
    """headless='virtual' reaches its Xvfb without repointing the whole process at it.

    Teeth on both halves. DISPLAY is set to a display that does not exist, so a
    launch falling back to the ambient value could not start Firefox at all: the env
    mode is pinned to 'true' (which never touches a display), so a successful navigate
    proves the per-call param drove the launch into virtual mode AND that the
    throwaway Xvfb display reached the browser through the launch's own env. The pin is
    explicit because the helper otherwise inherits an ambient CAMOUFOX_HEADLESS, and an
    ambient 'virtual' would make this pass without the param doing anything.

    Then DISPLAY is unchanged afterwards. Camoufox defaults its ``env`` option to a
    reference to ``os.environ`` and writes DISPLAY into it, so before issue #5 this
    left the server process pointed at a 1x1 Xvfb for the rest of its life, and a
    visible session created later inherited it.
    """
    if shutil.which("Xvfb") is None:
        pytest.skip("Xvfb is not installed; cannot exercise virtual display mode")

    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_HEADLESS="true")
    monkeypatch.setenv("DISPLAY", _ABSENT_DISPLAY)

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
    assert os.environ["DISPLAY"] == _ABSENT_DISPLAY, (
        "a virtual session must not repoint the server process at its Xvfb display"
    )


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

    The env mode is pinned to 'true'; the second navigate asks for 'virtual' but the
    session already exists, so it is silently ignored (and no Xvfb is ever spawned,
    hence no Xvfb guard here). The 'options ignored' note must name headless. Pinning
    the mode keeps both halves true under an ambient CAMOUFOX_HEADLESS=virtual run,
    where the first navigate would otherwise need an Xvfb of its own.
    """
    isolate_camoufox_env(monkeypatch, data_dir, CAMOUFOX_HEADLESS="true")

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
