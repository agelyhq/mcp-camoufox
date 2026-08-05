"""A selector list matches the union of its branches, priced on a big document.

Split out of tests/test_waiting.py, which pins the waiting itself. The shapes here
are the real ones from the usage record, and what each one must match is decided by
a reference walk run in the page, never by a hand-written list.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, call_within, evaluate, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# Guardrails, not measurements: only a call that never comes back reaches them.
_MATCHES_AT_ONCE_GUARDRAIL_S = 20.0
_PASS_GUARDRAIL_S = 60.0

# One query pass per selector branch, and the click below carries 2 branches. A poll
# that burned its 5s budget at the 50ms interval would run 2 orders of magnitude more,
# so the ceiling separates the 2 outcomes without touching a clock.
_MAX_PASSES = 8
_COUNT_QUERY_PASSES_JS = """
(() => {
  window.__passes = 0;
  const original = Document.prototype.querySelectorAll;
  Document.prototype.querySelectorAll = function (selector) {
    window.__passes++;
    return original.call(this, selector);
  };
  return 1;
})()
"""

# Real selector shapes from the usage record, each paired with what it means: one
# CSS part per comma branch plus the texts every match of THAT branch must contain.
# A selector list matches the union of its branches, so the pairing is the spec.
_BRANCH_CASES = (
    ('.alpha, .go:has-text("Prêt")', ((".alpha", ()), (".go", ("Prêt",)))),
    (
        '.go:has-text("Prêt"), [role=option]:has-text("Quick fight")',
        ((".go", ("Prêt",)), ("[role=option]", ("Quick fight",))),
    ),
    (
        ".leave-modal button:has-text('Quitter'), "
        "[class*=\"leave-modal\"] button:has-text('Quitter')",
        ((".leave-modal button", ("Quitter",)), ('[class*="leave-modal"] button', ("Quitter",))),
    ),
    (
        ".roster button, button:has-text('RENOMMER'), [class*=rename]",
        ((".roster button", ()), ("button", ("RENOMMER",)), ("[class*=rename]", ())),
    ),
    (
        "button.metal-plate.ready-btn, button:has-text('Prêt'):not([disabled])",
        (("button.metal-plate.ready-btn", ()), ("button:not([disabled])", ("Prêt",))),
    ),
    ('button:has-text("a >> b")', (("button", ("a >> b",)),)),
    ('[role=option]:has-text("Show :visible rows")', (("[role=option]", ("Show :visible rows",)),)),
    ('[data-tag="a,b"]', (('[data-tag="a,b"]', ()),)),
    ('button:has-text("Yes, now")', (("button", ("Yes, now",)),)),
)

# The reference: walk the document once, keep an element as soon as ONE branch takes
# it. Deliberately not a parser, so it cannot repeat a parser's mistake.
_REFERENCE = r"""(() => {
  const branches = %s;
  const norm = (v) => String(v == null ? '' : v).replace(/\s+/g, ' ').trim().toLowerCase();
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    for (const branch of branches) {
      if (!el.matches(branch[0])) continue;
      const text = norm(el.textContent);
      let every = true;
      for (const needle of branch[1]) {
        if (text.indexOf(norm(needle)) === -1) every = false;
      }
      if (every) {
        out.push(el.getAttribute('data-m') || ('<' + el.tagName.toLowerCase() + '>'));
        break;
      }
    }
  }
  return out;
})()"""


async def _page_markers(client: Client) -> set[str]:
    """Every marker the page carries, read off the page rather than hard-coded."""
    listed = await evaluate(
        client,
        PROFILE,
        "[...document.querySelectorAll('[data-m]')].map((el) => el.getAttribute('data-m'))",
    )
    return set(json.loads(listed))


def _markers_of(rendered: str, markers: set[str]) -> list[str]:
    """The markers named by a ``find`` result, in the order it rendered them."""
    return [token for token in re.findall(r"[a-z]\d", rendered) if token in markers]


async def _reference_markers(client: Client, branches: object) -> list[str]:
    return json.loads(await evaluate(client, PROFILE, _REFERENCE % json.dumps(branches)))


async def test_selector_list_matches_the_union_of_its_branches(
    client: Client, flask_server: str
) -> None:
    """Each comma branch carries its own :has-text; the result is their union.

    The shapes are the real ones from the usage record, and the expected set comes
    from a reference walk run in the page, not from a hand-written list.
    """
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/selector-branches", "profile": PROFILE}
    )

    markers = await _page_markers(client)
    assert len(markers) == 18, f"the page carries {len(markers)} markers, not 18"

    mismatches = []
    for selector, branches in _BRANCH_CASES:
        found = tool_text(
            await client.call_tool("find", {"profile": PROFILE, "css": selector, "limit": 50})
        )
        expected = await _reference_markers(client, branches)
        assert expected, f"the reference matched nothing for {selector}, so nothing was compared"
        if found.startswith("Error") or _markers_of(found, markers) != expected:
            mismatches.append(f"{selector} -> {found!r} instead of {expected}")

    assert not mismatches, "\n".join(mismatches)


async def test_click_and_wait_for_see_every_branch(client: Client, flask_server: str) -> None:
    """A branch selector must act, not burn its budget while 3 elements match.

    "the click took under 4s" priced the runner. What decides it is the number of
    query passes the click's poll made: matching at once is one pass, burning the 5s
    budget at a 50ms interval is around a hundred. The counter is installed before
    the store boots, so 00_boot.js captures it and every pass 45_query.js runs is
    counted, whichever selector branch it is querying.
    """
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/selector-branches", "profile": PROFILE}
    )
    assert await evaluate(client, PROFILE, _COUNT_QUERY_PASSES_JS) == "1"
    selector = '.go:has-text("Prêt"), [role=option]:has-text("Quick fight")'

    waited = tool_text(
        await client.call_tool(
            "wait_for",
            {"profile": PROFILE, "condition": "selector", "selector": selector, "timeout": 3000},
        )
    )
    assert waited.startswith("Condition met: selector"), waited

    await evaluate(client, PROFILE, "window.__passes = 0")
    clicked = await call_within(
        client, "click", {"profile": PROFILE, "selector": selector}, _MATCHES_AT_ONCE_GUARDRAIL_S
    )
    passes = int(await evaluate(client, PROFILE, "window.__passes"))
    # The lower bound keeps the upper one honest: a counter that never fires (a store
    # booted before the hook, a query path that stopped going through it) would read 0
    # and satisfy any ceiling.
    assert 1 <= passes <= _MAX_PASSES, (
        f"the click ran {passes} query passes for a selector that matches at once, so it "
        "polled instead of acting, or the pass counter is no longer wired to the query"
    )

    assert clicked.startswith("Clicked <button>"), clicked
    assert "b1 clicked" in await text_content(client, PROFILE, "branch-output")


async def test_locate_prices_a_large_document(client: Client, flask_server: str) -> None:
    """Both whole-document passes answer within the product's own ceiling on 12000 nodes.

    This used to assert 1s for the walk and 0.5s for the smallest-match pass. Those
    numbers priced the runner, not the code: the product promises a pass bounded by
    OP_TIMEOUT, never a sub-second one, so a loaded machine failed a correct
    implementation. What decides the cost is asserted instead: one pass over the whole
    document, all 4000 matches counted, 3 of them serialized. A pass that degraded into
    per-element round trips would exhaust the ceiling and come back as ``Timeout:``,
    which the exact result assertions below refuse. The seconds each pass took are
    carried in the assertion messages, where a reader of a failing run needs them.
    """
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/selector-large", "profile": PROFILE}
    )
    nodes = int(await evaluate(client, PROFILE, "document.querySelectorAll('*').length"))
    assert nodes > 1500, f"the page holds only {nodes} nodes"

    started = time.monotonic()
    walk = await call_within(
        client, "find", {"profile": PROFILE, "role": "button", "limit": 3}, _PASS_GUARDRAIL_S
    )
    walk_seconds = time.monotonic() - started
    assert "[found 3/4000]" in walk, f"whole-document walk took {walk_seconds:.2f}s: {walk}"

    started = time.monotonic()
    # 8001 elements contain "label" before the smallest-match pass narrows them to
    # the 4000 innermost ones, so this is that pass at its worst.
    smallest = await call_within(
        client, "find", {"profile": PROFILE, "css": "text=label", "limit": 3}, _PASS_GUARDRAIL_S
    )
    text_seconds = time.monotonic() - started
    assert "[found 3/4000]" in smallest, f"smallest-match pass took {text_seconds:.2f}s: {smallest}"
