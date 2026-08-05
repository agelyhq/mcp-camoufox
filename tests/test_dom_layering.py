"""The seams between a tool, ``dom/`` and the element store behind a page.

Four rules are pinned here, and each one has already been broken once.

A page operation with no Python caller is not free: the bundle is re-evaluated in
every document, so a dead op is bytes crossing the protocol on every navigation and
one more entry a page reading ``window.eval`` gets to see. It also invites the
reverse mistake, an op kept alive for a caller that never arrives.

A tool addressing ``page.elements`` itself skips the layer that owns uid semantics,
error translation and the poll. The rule is one-way: tools talk to ``dom/``, and
only ``dom/`` talks to the store.

An interactivity test written twice drifts. It already did: the walk grew its own
copy so it could leave ``cursor: pointer`` out, and the two definitions then had
5 identical lines that nothing kept in step.

And a bundle file that reaches the page's own iterator or array methods hands the
page a tally of our work. That one is a source assertion because it cannot be proven
live: the driver rebuilds every argument array through the same built-ins before our
code runs, so replacing them fails the call upstream of us.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from camoufox_mcp import dom, tools
from camoufox_mcp.dom import identity
from camoufox_mcp.dom.identity import locate_many
from camoufox_mcp.dom.source import OPS

_JS_DIR = Path(dom.__file__).resolve().parent / "js"
_TOOLS_DIR = Path(tools.__file__).resolve().parent

# The lines ``isInteractive`` and ``ownsInteraction`` used to state twice.
_SHARED_SIGNALS = (
    "B.toInt(el.getAttribute('tabindex'), 10)",
    "el.getAttribute('contenteditable') !== 'false'",
    "el.hasAttribute('onclick')",
)

_FOR_OF = re.compile(r"\bfor\s*\(\s*(?:const|let|var)\s+\w+\s+of\b")
# The page's own array methods, called on a value our code owns. ``.push`` on an array
# we built is still ``Array.prototype.push``, so a page that replaces it gets a tally
# of every match we collect. Plain index writes (``out[out.length] = x``) do not.
_ARRAY_METHOD = re.compile(r"\.(push|pop|shift|unshift|filter|map|forEach|sort|some|every)\(")


class _Store:
    """The element store of one tab, answering one scripted payload per call."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, op: str, arg: dict[str, Any] | None = None, **_: Any) -> Any:
        self.calls.append((op, dict(arg or {})))
        return self._payload


class _Page:
    def __init__(self, payload: Any) -> None:
        self.elements = _Store(payload)


def _js(name: str) -> str:
    return (_JS_DIR / name).read_text(encoding="utf-8")


def test_the_describe_operation_is_gone_from_every_layer() -> None:
    """It lost its only caller when get_element moved to its 7 documented properties.

    The scan covers every JS file, not just the dispatch table. The op entry went first
    and the function body stayed behind for a release, still concatenated into a bundle
    re-evaluated in every document: unreachable, but paid for on every navigation and
    visible to anything reading the store. A layer-by-layer assertion is what makes the
    dead-op rule this module states actually enforceable.
    """
    assert "describe" not in OPS
    assert not hasattr(identity, "describe_uid")
    assert "describe_uid" not in dom.__all__
    offenders = sorted(
        path.name
        for path in _JS_DIR.rglob("*.js")
        if "describeEl" in path.read_text(encoding="utf-8")
    )
    assert offenders == []


def test_no_bundle_file_reaches_the_page_through_an_array_or_an_iterator() -> None:
    """``for...of`` and every ``Array.prototype`` method resolve on the page's own
    prototypes at call time, so a page that replaces one both sees and can break the
    walk.

    Every file of the bundle is scanned, not a chosen few. The selector path was the
    one exception for a while, and it is the path behind ``find`` and behind every
    selector-bound click and fill, which is exactly where a count is worth having.
    """
    for path in sorted(_JS_DIR.glob("*.js")):
        source = path.read_text(encoding="utf-8")
        assert not _FOR_OF.search(source), f"{path.name} iterates through the page's own protocol"
        found = _ARRAY_METHOD.search(source)
        assert found is None, f"{path.name} calls the page's own {found.group(1)}()"


def test_no_tool_addresses_the_element_store_directly() -> None:
    """A tool reaching past dom/ skips uid semantics, error translation and the poll."""
    offenders = sorted(
        path.name
        for path in _TOOLS_DIR.glob("*.py")
        if ".elements" in path.read_text(encoding="utf-8")
    )
    assert offenders == []


def test_the_interactivity_signals_are_written_once() -> None:
    """isInteractive is ownsInteraction plus the cursor test, not a second copy of it."""
    whole = "\n".join(_js(path.name) for path in sorted(_JS_DIR.glob("*.js")))
    for signal in _SHARED_SIGNALS:
        assert whole.count(signal) == 1, signal
    assert "ownsInteraction(el)" in _js("10_visibility.js")


async def test_locate_many_hands_a_tool_the_uids_and_the_total() -> None:
    """One store call carries the caller's limit; the total is what matched before it."""
    page = _Page({"ok": True, "ids": ["e1", "e2"], "total": 5})

    assert await locate_many(page, ".row", limit=2, deadline=0.0) == (["e1", "e2"], 5)
    assert page.elements.calls == [
        ("locate", {"selector": ".row", "visible": True, "limit": 2, "mint": True})
    ]


async def test_locate_many_names_the_selector_that_matched_nothing() -> None:
    page = _Page({"ok": True, "ids": [], "total": 0})

    with pytest.raises(ValueError) as raised:
        await locate_many(page, ".row", limit=3, deadline=0.0)

    assert str(raised.value) == "no element matches '.row'"
