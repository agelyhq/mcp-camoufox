from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, extract_uid, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


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
