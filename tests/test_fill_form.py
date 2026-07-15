from __future__ import annotations

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
    assert "3" in result
    assert "filled" in result.lower()

    js = await evaluate(
        client,
        PROFILE,
        "JSON.stringify([document.getElementById('ff-first').value,"
        "document.getElementById('ff-last').value,"
        "document.getElementById('ff-city').value])",
    )
    assert "Ada" in js
    assert "Lovelace" in js
    assert "London" in js


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
    assert "error" in result.lower()
