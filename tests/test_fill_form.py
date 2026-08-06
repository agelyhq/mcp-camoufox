from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, STALE_UID, evaluate, extract_uid, snapshot_text, tool_text
from tests.waits import poll_tool_until

if TYPE_CHECKING:
    from fastmcp import Client

_ABSENT_UID = "e999999"


async def test_fill_form_multiple_fields(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill-form", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    first = extract_uid(snap, "First name")
    last = extract_uid(snap, "Last name")
    city = extract_uid(snap, "City")

    result = tool_text(
        await client.call_tool(
            "fill_form",
            {
                "profile": PROFILE,
                "fields": [
                    {"uid": first, "value": "Ada"},
                    {"uid": last, "value": "Lovelace"},
                    {"uid": city, "value": "London"},
                ],
            },
        )
    )
    assert result == "Filled 3 field(s)", result

    # Exact values in exact fields: three substring checks over one blob would also
    # pass if every value had landed in the same input.
    js = await evaluate(
        client,
        PROFILE,
        "JSON.stringify([document.getElementById('ff-first').value,"
        "document.getElementById('ff-last').value,"
        "document.getElementById('ff-city').value])",
    )
    assert json.loads(json.loads(js)) == ["Ada", "Lovelace", "London"], js


async def test_fill_form_malformed_entry(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/fill-form", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    first = extract_uid(snap, "First name")

    result = tool_text(
        await client.call_tool(
            "fill_form",
            {"profile": PROFILE, "fields": [{"uid": first}]},
        )
    )
    # The index is the whole point: out of a 6-field call, "error" somewhere in the
    # string leaves the caller retrying them one at a time to find the bad one.
    assert result == "Error: ValueError: field 0 needs 'uid' and 'value'", result


async def test_fill_form_handles_a_checkbox(client: Client, flask_server: str) -> None:
    """A checkbox inside the form no longer makes the whole call a silent no-op."""
    await client.call_tool("navigate", {"url": f"{flask_server}/fill-form", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    result = tool_text(
        await client.call_tool(
            "fill_form",
            {
                "profile": PROFILE,
                "fields": [
                    {"uid": extract_uid(snap, "First name"), "value": "Grace"},
                    {"uid": extract_uid(snap, "Subscribe"), "value": "true"},
                ],
            },
        )
    )
    assert result == "Filled 2 field(s)", result

    js = await evaluate(
        client,
        PROFILE,
        "JSON.stringify([document.getElementById('ff-first').value,"
        "document.getElementById('ff-optin').checked])",
    )
    assert json.loads(json.loads(js)) == ["Grace", True], js


async def test_fill_form_names_the_field_a_stale_uid_came_from(
    client: Client, flask_server: str
) -> None:
    """The position is added to a rejected value, and nothing else is changed about it.

    The mandated stale-uid string has to survive verbatim inside the annotated message,
    because that string is what tells the agent to re-snapshot, and it has to arrive with
    the index because "field 1" is the only thing that says which of the pair was wrong.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/fill-form", "profile": PROFILE})
    snap = await snapshot_text(client)
    first = extract_uid(snap, "First name")

    result = tool_text(
        await client.call_tool(
            "fill_form",
            {
                "profile": PROFILE,
                "fields": [
                    {"uid": first, "value": "Ada"},
                    {"uid": _ABSENT_UID, "value": "nowhere"},
                ],
            },
        )
    )

    expected = STALE_UID.format(uid=_ABSENT_UID)
    assert result == f"Error: ValueError: field 1 (uid '{_ABSENT_UID}'): {expected}", result


async def test_fill_form_on_a_dead_tab_keeps_the_exception_class(
    client: Client, flask_server: str
) -> None:
    """A closed tab is a TargetClosedError here as much as anywhere else.

    ``_fill_one`` used to catch every exception and re-raise ``ValueError``, so this call
    answered "Error: ValueError: field 0 (uid ...)" for a browser tab that no longer
    existed. 2 things went with the class. A ``TimeoutError`` stopped rendering as the
    mandated "Timeout: ..." and started reading as a rejected argument, and an
    off-contract type stopped leaving a traceback in the server log, which is the shape
    that left a 133-occurrence ``UnicodeDecodeError`` unexplained for a month.

    The field index is still owed on a rejected value (the scenario above), so the
    assertion here is that it is NOT bolted onto this one: the index describes the
    request, and the tab being gone is not about the request.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/fill-form", "profile": PROFILE})
    await client.call_tool("new_page", {"profile": PROFILE, "url": f"{flask_server}/fill-form"})
    uid = extract_uid(await snapshot_text(client), "First name")

    await evaluate(client, PROFILE, "window.close()")
    # The close crosses the protocol asynchronously, so a fill sent while the tab is
    # still alive succeeds and proves nothing. Probe until it stops answering: that is
    # the precondition, and the fill below is the assertion.
    await poll_tool_until(
        client,
        "evaluate",
        {"profile": PROFILE, "script": "1"},
        lambda text: "TargetClosedError" in text,
        describe="the closed tab never stopped answering evaluate",
    )

    result = tool_text(
        await client.call_tool(
            "fill_form", {"profile": PROFILE, "fields": [{"uid": uid, "value": "Ada"}]}
        )
    )

    assert result.startswith("Error: TargetClosedError:"), result
    assert "field 0" not in result
    assert "take a new snapshot" not in result
