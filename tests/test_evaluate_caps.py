"""Output caps and serialization guards on ``evaluate``.

The tool is the most called one in the product and was the only one returning page
content with no cap at all: one real call put 353120 characters straight into a
model's context. These scenarios pin both caps, the item boundary that keeps a
truncated array parseable, and the values the page cannot hand over at all.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.evaluate_helpers import capped, evaluate_uids, uids_for_labels
from tests.helpers import PROFILE, evaluate, open_page

if TYPE_CHECKING:
    from fastmcp import Client

# 5341 small objects: the item cap binds well before the character cap.
_MANY_ITEMS_JS = "Array.from({length: 5341}, (_, i) => ({i: i, t: 'abcdefghij'}))"
# 50 fat strings: only the character cap can bind, and it must still cut cleanly.
_FAT_ITEMS_JS = "Array.from({length: 50}, () => 'y'.repeat(2000))"
_BIG_STRING_JS = "'z'.repeat(50000)"
_CIRCULAR_JS = "(() => { const a = {}; a.self = a; return a; })()"


def _split(result: str) -> tuple[str, str]:
    """Split a capped result into its JSON body and its single truncation note.

    JSON escapes every control character, so the only literal newline a capped
    result can contain is the one this helper cuts on.
    """
    body, newline, note = result.partition("\n")
    assert newline, f"expected a truncation note, got: {result[:200]}"
    return body, note


async def test_evaluate_small_results_are_untouched(client: Client, flask_server: str) -> None:
    """The caps are optional and change nothing below them, byte for byte."""
    await open_page(client, f"{flask_server}/evaluate")

    assert await evaluate(client, PROFILE, "[1, 2, 3]") == "[1, 2, 3]"
    assert await evaluate(client, PROFILE, "({a: 1, b: 'x'})") == '{"a": 1, "b": "x"}'
    assert await evaluate(client, PROFILE, "'hello'") == '"hello"'
    assert await evaluate(client, PROFILE, "undefined") == "null"


async def test_evaluate_array_is_cut_at_the_item_boundary(
    client: Client, flask_server: str
) -> None:
    """The whole point of max_items: what comes back is still a parseable array."""
    await open_page(client, f"{flask_server}/evaluate")

    body, note = _split(await evaluate(client, PROFILE, _MANY_ITEMS_JS))

    items = json.loads(body)
    assert len(items) == 200
    assert items[0] == {"i": 0, "t": "abcdefghij"}
    assert items[-1] == {"i": 199, "t": "abcdefghij"}
    assert note == "[truncated: showing 200 of 5341 items. Raise max_items to see more]"


async def test_evaluate_max_items_is_adjustable(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/evaluate")

    body, note = _split(await capped(client, _MANY_ITEMS_JS, max_items=5))

    assert [item["i"] for item in json.loads(body)] == [0, 1, 2, 3, 4]
    assert note == "[truncated: showing 5 of 5341 items. Raise max_items to see more]"


async def test_evaluate_char_cap_also_cuts_an_array_at_the_item_boundary(
    client: Client, flask_server: str
) -> None:
    """50 items is under max_items, so only max_chars can bind, and it names itself."""
    await open_page(client, f"{flask_server}/evaluate")

    body, note = _split(await evaluate(client, PROFILE, _FAT_ITEMS_JS))

    items = json.loads(body)
    assert 0 < len(items) < 50
    assert len(body) <= 20000
    assert note == f"[truncated: showing {len(items)} of 50 items. Raise max_chars to see more]"


async def test_evaluate_string_is_cut_at_max_chars(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/evaluate")

    body, note = _split(await evaluate(client, PROFILE, _BIG_STRING_JS))

    assert len(body) == 20000
    assert note == (
        "[truncated: showing 20000 of 50002 chars. Cut mid-value, so this is a "
        "fragment and not valid JSON. Raise max_chars to see more]"
    )


async def test_evaluate_caps_can_be_disabled(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/evaluate")

    result = await capped(client, _BIG_STRING_JS, max_chars=0)

    assert len(result) == 50002
    assert "truncated" not in result


async def test_evaluate_caps_apply_on_the_uid_path(client: Client, flask_server: str) -> None:
    (uid,) = await uids_for_labels(client, flask_server, "Click me")

    body, note = _split(
        await evaluate_uids(client, "(el) => Array.from({length: 5341}, (_, i) => i)", [uid])
    )

    assert json.loads(body) == list(range(200))
    assert note == "[truncated: showing 200 of 5341 items. Raise max_items to see more]"


async def test_evaluate_dom_node_is_named_not_rendered(client: Client, flask_server: str) -> None:
    """Measured: the driver returns the literal text 'ref: <Node>' and raises nothing."""
    await open_page(client, f"{flask_server}/evaluate")

    result = await evaluate(client, PROFILE, "document.body")

    assert result.startswith("Error: ValueError: script returned a DOM node, which cannot be")
    assert "el.textContent" in result
    assert "ref: <Node>" not in result


async def test_evaluate_nested_dom_node_names_its_path(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/evaluate")

    result = await evaluate(client, PROFILE, "({ok: 1, el: document.body})")

    assert "script returned a DOM node at result.el" in result


async def test_evaluate_circular_result_is_named(client: Client, flask_server: str) -> None:
    """Measured: the driver rebuilds the cycle in Python, where json.dumps refuses it."""
    await open_page(client, f"{flask_server}/evaluate")

    result = await evaluate(client, PROFILE, _CIRCULAR_JS)

    assert result == (
        "Error: ValueError: script returned a circular structure, which cannot be "
        "serialized; return a plain copy of the fields you need instead"
    )
