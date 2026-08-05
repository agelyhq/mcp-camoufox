"""The one page-visible artifact this server cannot prevent, pinned on purpose.

:mod:`tests.test_no_markers` claims our own footprint is empty. That claim has a
driver-level boundary, and this module measures where it sits instead of assuming it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.helpers import PROFILE, evaluate, open_page
from tests.probes import (
    INTERCEPTOR_EVENTS,
    arm_probes,
    probe_server,
    probes_after_the_leak_window,
    probes_when,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client, FastMCP

LOG_STRING_JS = "(() => { console.log('plain string'); return 1; })()"
LOG_NODE_JS = "(() => { console.log(document.body); return 1; })()"


@pytest.fixture
def mcp_server(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> FastMCP:
    return probe_server(monkeypatch, data_dir)


async def test_node_valued_console_argument_forces_the_driver_injected_script(
    client: Client, flask_server: str
) -> None:
    """Page script that logs a DOM node makes the driver instantiate its injected script.

    When page code logs a DOM node, the Firefox driver builds an element handle for that
    argument inside its own console handler (coreBundle.js:43478 ``_onConsole`` -> :42843
    ``createHandle3`` -> :16039 the ``ElementHandle`` constructor), and the constructor
    evaluates the driver's injected script into the world the node lives in, which
    installs its branded listener set on window. The handles are built while calling
    ``addConsoleMessage`` (:19925), which only afterwards checks whether anyone
    subscribed, so dropping this server's console capture changes nothing. There is no
    supported client-side switch for it.

    Logging a string on the same page is the control, so neither half of this can pass by
    accident. If the node case ever stops leaking, this test fails: that is the signal to
    tighten the invariant in CLAUDE.md and the wording in docs/anti-bot.md.
    """
    await open_page(client, f"{flask_server}/probe")
    await arm_probes(client)

    assert await evaluate(client, PROFILE, LOG_STRING_JS) == "1"
    control = await probes_after_the_leak_window(client)
    assert control["listeners"] == [], f"a string argument leaked: {control['listeners']}"
    assert control["mo"] == 0

    assert await evaluate(client, PROFILE, LOG_NODE_JS) == "1"
    probes = await probes_when(
        client,
        lambda p: (
            any("__playwright_global_listeners_check__" in t for t in p["listeners"])
            and all(t in p["listeners"] for t in INTERCEPTOR_EVENTS)
            and p["mo"] == 1
        ),
    )
    assert any("__playwright_global_listeners_check__" in t for t in probes["listeners"]), (
        "the driver no longer instantiates its injected script for a node-valued "
        f"console argument: tighten the invariant and the docs. Got {probes['listeners']}"
    )
    assert all(t in probes["listeners"] for t in INTERCEPTOR_EVENTS), probes["listeners"]
    assert probes["mo"] == 1, probes["mo"]
