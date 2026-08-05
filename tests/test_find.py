"""`find`: reach a few elements without paying for a whole snapshot.

It mints through the same table the snapshot walk uses, so a uid from a find and a
uid from a snapshot are the same uid for the same element.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, text_content, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


# Two controls whose accessible name ends in brackets of its own, one of them
# disabled so the walk appends a bracketed attribute group to its line as well.
_ADD_BRACKETED_NAMES_JS = """
(() => {
  for (const locked of [false, true]) {
    const button = document.createElement('button');
    button.textContent = 'Save (draft)';
    button.disabled = locked;
    document.body.appendChild(button);
  }
  return 1;
})()
"""

# A name that is nothing but a bracketed group.
_ADD_BRACKET_ONLY_NAME_JS = """
(() => {
  const button = document.createElement('button');
  button.textContent = '(new)';
  document.body.appendChild(button);
  return 1;
})()
"""

# More whole-value matches than a whole-value search looks through.
_ADD_MANY_SAVE_BUTTONS_JS = """
(() => {
  for (let i = 0; i < 120; i++) {
    const button = document.createElement('button');
    button.textContent = 'Save';
    document.body.appendChild(button);
  }
  return 1;
})()
"""


async def _goto(client: Client, flask_server: str, path: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}{path}", "profile": PROFILE})


async def _open(client: Client, flask_server: str, path: str = "/click") -> str:
    await _goto(client, flask_server, path)
    return tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))


async def _find(client: Client, **filters: object) -> str:
    return tool_text(await client.call_tool("find", {"profile": PROFILE, **filters}))


async def test_find_by_role_and_name(client: Client, flask_server: str) -> None:
    """The flagship query, and proof that locating an element does not act on it."""
    await _open(client, flask_server)

    result = await _find(client, role="button", name="Count clicks")

    assert result.startswith("[found 1/1]")
    assert "Count clicks" in result
    counter = await text_content(client, PROFILE, "counter-output")
    assert json.loads(counter) == "Clicked 0 time(s)", counter


async def test_find_uid_matches_the_snapshot_uid(client: Client, flask_server: str) -> None:
    snap = await _open(client, flask_server)

    result = await _find(client, css="#btn-counter")

    assert extract_uid(result, "Count clicks") == extract_uid(snap, "Count clicks")


async def test_find_uid_is_actionable(client: Client, flask_server: str) -> None:
    """A uid minted by find drives a click without any snapshot in between."""
    await _goto(client, flask_server, "/click")

    result = await _find(client, text="Count clicks", role="button")
    uid = extract_uid(result, "Count clicks")

    clicked = tool_text(await client.call_tool("click", {"profile": PROFILE, "uid": uid}))
    assert clicked.startswith("Clicked <button>")
    counter = await text_content(client, PROFILE, "counter-output")
    assert json.loads(counter) == "Clicked 1 time(s)", counter


async def test_find_uid_fills_without_a_snapshot(client: Client, flask_server: str) -> None:
    """The same uid feeds `fill`, which resolves it through the same table."""
    await _goto(client, flask_server, "/find")

    result = await _find(client, label="Email address")
    uid = extract_uid(result, "Email address")

    filled = tool_text(
        await client.call_tool("fill", {"profile": PROFILE, "uid": uid, "value": "ada@example.com"})
    )
    assert filled.startswith("Filled")
    value = await evaluate(client, PROFILE, "document.getElementById('email').value")
    assert json.loads(value) == "ada@example.com", value


async def test_find_by_label_placeholder_and_test_id(client: Client, flask_server: str) -> None:
    await _goto(client, flask_server, "/find")

    labelled = await _find(client, label="Email address")
    held = await _find(client, placeholder="search")
    tagged = await _find(client, test_id="checkout-button")

    assert labelled.startswith("[found 1/1]")
    assert "input:email" in labelled
    assert "Email address" in labelled
    assert held.startswith("[found 1/1]")
    assert "input:search" in held
    assert "Search products" in held
    assert tagged.startswith("[found 1/1]")
    assert "[button" in tagged
    assert "Go" in tagged


async def test_find_by_text_lists_every_match(client: Client, flask_server: str) -> None:
    await _goto(client, flask_server, "/find")

    result = await _find(client, text="Add to cart")

    lines = result.splitlines()
    assert lines[0] == "[found 3/3]"
    assert lines[1].startswith("[button ")
    assert lines[2].endswith("(disabled)")
    assert "Add to cart later" in lines[3]


async def test_find_exact_narrows_to_the_whole_name(client: Client, flask_server: str) -> None:
    await _goto(client, flask_server, "/find")

    loose = await _find(client, text="Add to cart")
    strict = await _find(client, text="Add to cart", exact=True)
    wrong_case = await _find(client, text="add to cart", exact=True)

    assert loose.startswith("[found 3/3]")
    assert strict.startswith("[found 2/2]")
    assert "later" not in strict
    assert wrong_case == (
        'Error: ValueError: no element matches text "add to cart" (whole value, case-sensitive)'
    )


async def test_exact_keeps_every_name_that_ends_in_brackets(
    client: Client, flask_server: str
) -> None:
    """A name may end in brackets, and so may the attribute group after it.

    Both buttons are named `Save (draft)`, and the disabled one renders a second
    bracketed group. Telling the two apart by looking at the line is guesswork, and
    the guess used to drop the button that was actually usable.
    """
    await _goto(client, flask_server, "/find")
    assert await evaluate(client, PROFILE, _ADD_BRACKETED_NAMES_JS) == "1"

    result = await _find(client, name="Save (draft)", exact=True)

    lines = result.splitlines()
    assert lines[0] == "[found 2/2]", result
    assert len(lines) == 3, result
    assert not lines[1].endswith("(disabled)"), lines[1]
    assert lines[2].endswith("(disabled)"), lines[2]


async def test_exact_refuses_a_name_that_only_starts_with_the_value(
    client: Client, flask_server: str
) -> None:
    """`Save (draft)` is not `Save`, however alike the two rendered lines look."""
    await _goto(client, flask_server, "/find")
    assert await evaluate(client, PROFILE, _ADD_BRACKETED_NAMES_JS) == "1"

    result = await _find(client, name="Save", exact=True)

    assert result == (
        'Error: ValueError: no element matches name "Save" (whole value, case-sensitive)'
    )


async def test_exact_matches_a_name_that_is_only_brackets(
    client: Client, flask_server: str
) -> None:
    await _goto(client, flask_server, "/find")
    assert await evaluate(client, PROFILE, _ADD_BRACKET_ONLY_NAME_JS) == "1"

    result = await _find(client, text="(new)", exact=True)

    lines = result.splitlines()
    assert lines[0] == "[found 1/1]", result
    assert lines[1].endswith("] (new)"), lines[1]


async def test_exact_marks_a_total_it_could_not_finish_counting(
    client: Client, flask_server: str
) -> None:
    """Past the scan the total is a floor, and it says so rather than inventing one."""
    await _goto(client, flask_server, "/find")
    assert await evaluate(client, PROFILE, _ADD_MANY_SAVE_BUTTONS_JS) == "1"

    result = await _find(client, name="Save", exact=True, limit=3)

    lines = result.splitlines()
    assert lines[0] == "[found 3/100+]", result
    assert len(lines) == 4, result


async def test_find_names_what_the_role_matched(client: Client, flask_server: str) -> None:
    """The not-found report lists what the query actually saw, typo included."""
    await _goto(client, flask_server, "/find")

    result = await _find(client, role="heading", name="Skillz")

    assert result == (
        'Error: ValueError: no heading named "Skillz". 2 headings found, named: "Skills", "Home"'
    )


async def test_find_reports_the_criteria_when_nothing_matches(
    client: Client, flask_server: str
) -> None:
    await _goto(client, flask_server, "/find")

    result = await _find(client, role="slider", name="Volume")

    assert result == 'Error: ValueError: no element matches role "slider", name "Volume"'


async def test_find_states_the_total_beyond_the_limit(client: Client, flask_server: str) -> None:
    await _goto(client, flask_server, "/find")

    result = await _find(client, role="button", limit=2)

    assert result.startswith("[found 2/4]")
    assert len(result.splitlines()) == 3


async def test_find_rejects_two_candidate_sources(client: Client, flask_server: str) -> None:
    await _goto(client, flask_server, "/find")

    clash = await _find(client, css="button", test_id="checkout-button")
    duplicate = await _find(client, name="Email", label="Email address")

    assert clash == (
        "Error: ValueError: css, label and placeholder/test_id each choose the candidates; "
        "give only one of them"
    )
    assert duplicate == (
        "Error: ValueError: name and label both match the accessible name; give only one"
    )


async def test_find_requires_a_filter(client: Client, flask_server: str) -> None:
    await _open(client, flask_server)

    result = await _find(client)

    assert result == (
        "Error: ValueError: find needs at least one of role, name, text, label, "
        "placeholder, test_id or css"
    )


async def test_find_honours_the_limit(client: Client, flask_server: str) -> None:
    await _open(client, flask_server)

    result = await _find(client, role="button", limit=2)

    assert result.startswith("[found 2/")
    assert len(result.splitlines()) == 3
