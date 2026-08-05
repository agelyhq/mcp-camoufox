"""``get_element``: one property of one element, without writing a script for it.

Every scenario drives the real MCP surface against a real browser, because the
value of this tool is what the model receives as text, not what a helper returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import (
    PROFILE,
    RENDERED_STALE_UID,
    evaluate,
    extract_uid,
    open_page,
    tool_text,
)

if TYPE_CHECKING:
    from fastmcp import Client

# Three matches for one selector, the middle one of a kind that has no text to read.
_ADD_MIXED_MATCHES_JS = """
(() => {
  const wrap = document.createElement('div');
  wrap.innerHTML =
    '<p class="mixed">First note</p>' +
    '<input class="mixed" value="typed in">' +
    '<p class="mixed">Second note</p>';
  document.body.appendChild(wrap);
  return 1;
})()
"""


async def _get(client: Client, **args: object) -> str:
    return tool_text(await client.call_tool("get_element", {"profile": PROFILE, **args}))


async def test_text_reads_the_rendered_text(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    assert await _get(client, selector="#intro", prop="text") == (
        "Everything you need to know about this product."
    )
    # A closed select renders its selected option, and its innerText is empty.
    assert await _get(client, selector="#pick", prop="text") == "Banana"


async def test_text_is_capped_at_max_chars(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#long", prop="text", max_chars=40)

    head, note = result.split("\n")
    assert len(head) == 40
    assert note == "[truncated: showing 40 of 240 chars. Raise max_chars to see more]", note


async def test_value_reads_what_a_field_holds(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    assert await _get(client, selector="#email", prop="value") == "user@example.com"
    assert await _get(client, selector="#notes", prop="value") == "Deliver before noon"
    assert await _get(client, selector="#pick", prop="value") == "banana"


async def test_value_follows_a_fill_through_a_uid(client: Client, flask_server: str) -> None:
    """The empty field reads as empty, then reports exactly what fill typed into it."""
    await open_page(client, f"{flask_server}/get-element")
    found = tool_text(await client.call_tool("find", {"profile": PROFILE, "css": "#blank"}))
    uid = extract_uid(found, "Nickname")

    assert await _get(client, uid=uid, prop="value") == "(empty)"
    await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "Jo"})

    assert await _get(client, uid=uid, prop="value") == "Jo"


async def test_value_on_a_div_names_the_tag(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#plain", prop="value")

    assert result.startswith("Error: ValueError: element <div> has no value;")


async def test_text_on_an_input_points_at_value(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#email", prop="text")

    assert result == (
        "Error: ValueError: element <input> has no text; use prop='value' to read what it contains"
    )


async def test_attribute_reads_a_named_attribute(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    assert await _get(client, selector="#link", prop="attribute", name="href") == "/click"
    assert await _get(client, selector="#link", prop="attribute", name="data-role") == "nav"


async def test_absent_attribute_is_not_an_empty_string(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#link", prop="attribute", name="data-missing")

    assert result == "(not set)"


async def test_attribute_requires_a_name(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#link", prop="attribute")

    assert result == "Error: ValueError: prop='attribute' needs a name, e.g. name='href'"


async def test_state_reports_the_four_flags(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    assert await _get(client, selector="#locked", prop="state") == (
        "visible=true enabled=false checked=n/a editable=false"
    )
    assert await _get(client, selector="#agree", prop="state") == (
        "visible=true enabled=false checked=true editable=false"
    )
    assert await _get(client, selector="#email", prop="state") == (
        "visible=true enabled=true checked=n/a editable=true"
    )


async def test_a_match_without_the_property_is_a_note_not_a_dead_end(
    client: Client, flask_server: str
) -> None:
    """One match that cannot answer must not delete the answers of the others."""
    await open_page(client, f"{flask_server}/get-element")
    assert await evaluate(client, PROFILE, _ADD_MIXED_MATCHES_JS) == "1"

    result = await _get(client, selector=".mixed", prop="text", limit=3)

    assert result.splitlines() == [
        "1. First note",
        "2. element <input> has no text; use prop='value' to read what it contains",
        "3. Second note",
        "(3 of 3 matches)",
    ]


async def test_style_reads_a_computed_property(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#styled", prop="style", name="color")

    assert result == "rgb(255, 0, 0)"


async def test_style_rejects_an_unknown_property(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#styled", prop="style", name="colour")

    assert result == "Error: ValueError: no computed style named 'colour' on <p>"


async def test_count_returns_the_number_of_matches(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    assert await _get(client, selector="button.buy", prop="count") == "3"
    assert await _get(client, selector="#nowhere", prop="count") == "0"


async def test_count_refuses_a_uid(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, uid="e1", prop="count")

    assert result == "Error: ValueError: prop='count' needs a selector"


async def test_one_of_several_matches_says_so(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="button.buy", prop="text")

    assert result == "Buy A  (1 of 3 matches)"


async def test_limit_numbers_every_match(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="button.buy", prop="text", limit=3)

    assert result.splitlines() == ["1. Buy A", "2. Buy B", "3. Buy C", "(3 of 3 matches)"]


async def test_no_match_says_what_was_searched(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#nowhere", prop="text")

    assert result == "Error: ValueError: no element matches '#nowhere'"


async def test_stale_uid_asks_for_a_new_snapshot(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, uid="e999", prop="text")

    assert result == RENDERED_STALE_UID.format(uid="e999")


async def test_targeting_needs_exactly_one_address(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")
    expected = "Error: ValueError: provide exactly one of uid or selector"

    assert await _get(client, uid="e1", selector="#intro", prop="text") == expected
    assert await _get(client, prop="text") == expected


async def test_an_unknown_prop_lists_the_supported_ones(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-element")

    result = await _get(client, selector="#intro", prop="html")

    # The one enumeration message every tool that takes a closed set of words emits.
    assert result == (
        "Error: ValueError: invalid prop 'html'; valid values: "
        "'text', 'value', 'attribute', 'state', 'box', 'style', 'count'"
    )
