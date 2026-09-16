"""The one page-visible artifact this server cannot prevent, pinned on purpose.

:mod:`tests.test_no_markers` claims our own footprint is empty. That claim has a
driver-level boundary, and this module measures where it sits instead of assuming it.
"""

from __future__ import annotations

import ast
from pathlib import Path
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
    from fastmcp import Client, FastMCP

SRC = Path(__file__).resolve().parent.parent / "src" / "camoufox_mcp"
FILE_CHOOSER_EVENT = "filechooser"
# The driver's other doors onto the chooser, method names with no string literal to key
# on: each one subscribes to the event for the duration of its context.
FILE_CHOOSER_METHODS = frozenset({"expect_file_chooser", "wait_for_file_chooser"})
# What a tool may reach through ``Page.raw`` (CLAUDE.md, "Nothing we do is written to
# the page"): the input devices, the capture, and the two navigation waits.
RAW_ALLOWED = frozenset({"mouse", "keyboard", "screenshot", "goto", "wait_for_load_state"})


def _modules() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(SRC.rglob("*.py"))
    ]


def _attribute_hits(accept: object) -> list[str]:
    """Every ``x.attr`` under src that ``accept`` takes, as ``file:line``."""
    return [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path, module in _modules()
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute) and accept(node)
    ]


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


def test_nothing_under_src_subscribes_to_the_file_chooser() -> None:
    """The one driver event this server refuses on purpose, kept refused by reading the source.

    A ``filechooser`` subscription makes the driver build an element handle for the
    input behind the dialog, and that constructor instantiates the injected script in
    the page's main world: the same footprint the test above pins for a logged node,
    paid on every chooser a site opens. The decision is recorded in docs/decisions.md;
    this walks every module's AST for the event name so a listener cannot come back
    under any spelling of ``page.on(...)``, and a comment naming the event is not a hit.
    """
    hits = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path, module in _modules()
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and node.value == FILE_CHOOSER_EVENT
    ]
    assert hits == [], f"a filechooser subscription is back: {hits}"
    methods = _attribute_hits(lambda node: node.attr in FILE_CHOOSER_METHODS)
    assert methods == [], f"a filechooser wait is back: {methods}"


def test_page_raw_reaches_only_the_allowed_driver_surface() -> None:
    """``Page.raw`` is the one door onto the driver, and this pins what goes through it.

    The test above keys on the event's name; a ``page.raw.expect_file_chooser()`` names
    no event, and neither does any other driver method that addresses an element or
    writes to the page. So every ``<x>.raw.<attr>`` under src is read from the AST and
    ``attr`` must be one of the five the invariant lists; a new need is a change to the
    allowlist here and in CLAUDE.md, never a quiet sixth.
    """
    hits = _attribute_hits(
        lambda node: (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "raw"
            and node.attr not in RAW_ALLOWED
        )
    )
    assert hits == [], f"page.raw reaches outside {sorted(RAW_ALLOWED)}: {hits}"
    used = _attribute_hits(
        lambda node: (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "raw"
            and node.attr in RAW_ALLOWED
        )
    )
    assert used, "no page.raw access found under src: the walk is not seeing the code"
