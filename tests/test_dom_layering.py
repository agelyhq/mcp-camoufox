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

import pytest

from camoufox_mcp import dom, tools
from camoufox_mcp.dom import identity
from camoufox_mcp.dom.identity import locate_many
from camoufox_mcp.dom.source import OPS
from tests.fakes import ScriptedStorePage

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
# of every match we collect. Plain index writes (``out[out.length] = x``) do not, and a
# string is concatenated in the same index loop that built it.
#
# ``join`` is on this list because it was NOT, and that gap had teeth: the identity walk
# joined every name a field carries into the single string the secret test reads, so a
# page replacing ``Array.prototype.join`` could make a French "Mot de passe" field answer
# a benign string and have the typed password written to the log in clear.
#
# The list is meant to be exhaustive over the mutating and collection-producing half of
# ``Array.prototype``, minus 2 deliberate and named exclusions, so that "the list is
# short" is never the reason a name is missing:
#
# - Names ``String.prototype`` also carries are left out, which is what keeps the list
#   free of false positives: ``slice``, ``indexOf``, ``lastIndexOf``, ``includes`` and
#   ``at`` are legitimate and established on the strings this bundle parses (selectors,
#   text previews), and banning them by name would flag those. Array uses of THOSE are
#   avoided by convention instead — ``hitTest`` says so where it searches an array by
#   index. ``concat`` is the one name a string could take that is banned anyway: every
#   string here is built with ``+``, so a ``.concat(`` in this bundle is an array being
#   copied through the page.
# - ``entries``, ``keys`` and ``values`` are left out because the name does not identify
#   an array method: ``Object.entries(...)`` and the captured ``Map.prototype.entries``
#   (``B.mapEntries``, reached through ``.call(``) spell the same 7 letters. Their array
#   forms are only useful with ``for...of`` or a spread, both of which the iterator rule
#   above already refuses.
#
# Everything else is here, including the ES2023 additions: a guard whose contents and
# whose stated rule disagree is worse than either, and ``findLastIndex``, ``copyWithin``,
# ``toSorted``, ``toReversed``, ``toSpliced`` and ``with`` were missing while their
# neighbours were present.
_ARRAY_METHOD = re.compile(
    r"\.(join|concat|push|pop|shift|unshift|splice|reverse|fill|flat|flatMap|copyWithin"
    r"|map|filter|forEach|reduce|reduceRight|sort|some|every|find|findIndex|findLast"
    r"|findLastIndex|toSorted|toReversed|toSpliced|with)\("
)


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

    The scan recurses, so ``js/reads/`` is covered too. It was not, and the rules apply
    there with more force rather than less: a read is compiled by the page's own
    ``Function`` constructor and runs in the page's global scope, where not even the
    boot-time built-in table is reachable. What that gap held was the same defect as the
    ``join`` above — ``value.js`` chose inside ``els.map(...)`` whether a typed password
    is elided from the model's answer and from the record's ``result``.
    """
    for path in sorted(_JS_DIR.rglob("*.js")):
        name = path.relative_to(_JS_DIR).as_posix()
        source = path.read_text(encoding="utf-8")
        assert not _FOR_OF.search(source), f"{name} iterates through the page's own protocol"
        found = _ARRAY_METHOD.search(source)
        assert found is None, f"{name} calls the page's own {found.group(1)}()"


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
    page = ScriptedStorePage({"ok": True, "ids": ["e1", "e2"], "total": 5})

    assert await locate_many(page, ".row", limit=2, deadline=0.0) == (["e1", "e2"], 5)
    assert page.elements.calls == [
        ("locate", {"selector": ".row", "visible": True, "limit": 2, "mint": True})
    ]


async def test_locate_many_names_the_selector_that_matched_nothing() -> None:
    page = ScriptedStorePage({"ok": True, "ids": [], "total": 0})

    with pytest.raises(ValueError) as raised:
        await locate_many(page, ".row", limit=3, deadline=0.0)

    assert str(raised.value) == "no element matches '.row'"
