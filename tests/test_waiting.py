"""Auto-waiting survived the move off the driver's selector engine.

Resolving a selector with one synchronous query would turn every asynchronously
rendered page into an instant "no element matches". The Python-side poll is what
replaces it, and it also bounds the operations that were previously uncapped.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

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


async def _open(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/waiting", "profile": PROFILE})


async def test_click_selector_waits_for_a_late_element(client: Client, flask_server: str) -> None:
    await _open(client, flask_server)

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#late-btn"})
    )

    assert result.startswith("Clicked <button>"), result
    assert "#late-btn" in result
    assert "late button clicked" in await text_content(client, PROFILE, "late-output")


async def test_fill_selector_waits_for_a_late_field(client: Client, flask_server: str) -> None:
    await _open(client, flask_server)

    result = tool_text(
        await client.call_tool(
            "fill", {"profile": PROFILE, "selector": "#late-field", "value": "hello"}
        )
    )

    assert result.startswith("Filled <input>"), result
    assert "late field: hello" in await text_content(client, PROFILE, "late-output")


async def test_click_selector_expiry_message(client: Client, flask_server: str) -> None:
    await _open(client, flask_server)

    started = time.monotonic()
    result = tool_text(await client.call_tool("click", {"profile": PROFILE, "selector": "#never"}))
    elapsed = time.monotonic() - started

    assert result == (
        "Error: ValueError: no element matches selector '#never'; nothing matched at any "
        "point during the 5s wait, so check the selector, or wait for it first with "
        "wait_for(condition='selector', timeout=<ms>)"
    )
    assert elapsed < 10, f"the poll ran for {elapsed:.1f}s, well past its budget"


async def test_unsupported_selector_syntax_is_named(client: Client, flask_server: str) -> None:
    """A syntax we do not reimplement must say so, not silently match nothing."""
    await _open(client, flask_server)

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#a >> #b"})
    )

    assert "invalid selector '#a >> #b'" in result
    assert "chained engines (>>) is not supported" in result
    assert 'plain CSS, :has-text("..."), text=...' in result

    engine = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "role=button"})
    )
    assert "the role= engine is not supported" in engine


async def test_attribute_selectors_are_not_mistaken_for_engines(
    client: Client, flask_server: str
) -> None:
    """`[role=...]` and `[data-testid=...]` are ordinary CSS and must keep working."""
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": '[id="btn-counter"]'})
    )
    assert result.startswith("Clicked <button>"), result

    missing = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": '[data-testid="none"]'})
    )
    assert missing.startswith(
        "Error: ValueError: no element matches selector '[data-testid=\"none\"]'; "
    ), missing
    assert "nothing matched at any point during the 5s wait" in missing, missing


async def test_has_text_selector_filters_matches(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "click", {"profile": PROFILE, "selector": 'button:has-text("Count clicks")'}
        )
    )

    assert result.startswith("Clicked <button>"), result
    assert "1" in await text_content(client, PROFILE, "counter-output")


async def test_text_selector_matches_by_text_alone(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "text=Count clicks"})
    )

    assert result.startswith("Clicked <button>"), result
    assert "1" in await text_content(client, PROFILE, "counter-output")


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
    """A branch selector must act, not burn its budget while 3 elements match."""
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/selector-branches", "profile": PROFILE}
    )
    selector = '.go:has-text("Prêt"), [role=option]:has-text("Quick fight")'

    waited = tool_text(
        await client.call_tool(
            "wait_for",
            {"profile": PROFILE, "condition": "selector", "selector": selector, "timeout": 3000},
        )
    )
    assert waited.startswith("Condition met: selector"), waited

    started = time.monotonic()
    clicked = tool_text(await client.call_tool("click", {"profile": PROFILE, "selector": selector}))
    elapsed = time.monotonic() - started

    assert clicked.startswith("Clicked <button>"), clicked
    assert "b1 clicked" in await text_content(client, PROFILE, "branch-output")
    assert elapsed < 4, f"the click spent {elapsed:.1f}s on a selector that matches at once"


async def test_locate_prices_a_large_document(client: Client, flask_server: str) -> None:
    """Both whole-document passes stay far under the 15s ceiling on 12000 nodes."""
    await client.call_tool(
        "navigate", {"url": f"{flask_server}/selector-large", "profile": PROFILE}
    )
    nodes = int(await evaluate(client, PROFILE, "document.querySelectorAll('*').length"))
    assert nodes > 1500, f"the page holds only {nodes} nodes"

    started = time.monotonic()
    walk = tool_text(
        await client.call_tool("find", {"profile": PROFILE, "role": "button", "limit": 3})
    )
    walk_seconds = time.monotonic() - started
    assert "[found 3/4000]" in walk, walk

    started = time.monotonic()
    # 8001 elements contain "label" before the smallest-match pass narrows them to
    # the 4000 innermost ones, so this is that pass at its worst.
    smallest = tool_text(
        await client.call_tool("find", {"profile": PROFILE, "css": "text=label", "limit": 3})
    )
    text_seconds = time.monotonic() - started
    assert "[found 3/4000]" in smallest, smallest

    assert walk_seconds < 1, f"the whole-document walk took {walk_seconds:.2f}s"
    assert text_seconds < 0.5, f"the smallest-match pass took {text_seconds:.2f}s"


async def test_op_timeout_renders_as_timeout(client: Client, flask_server: str) -> None:
    """The one operation allowed to await is still bounded by a real clock."""
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    uid = extract_uid(snap, "Click me")

    started = time.monotonic()
    result = tool_text(
        await client.call_tool(
            "evaluate",
            {
                "profile": PROFILE,
                "script": "() => new Promise(() => {})",
                "uids": [uid],
            },
        )
    )
    elapsed = time.monotonic() - started

    assert result.startswith("Timeout:"), result
    assert 25 < elapsed < 45, f"the evaluate budget expired after {elapsed:.1f}s"
