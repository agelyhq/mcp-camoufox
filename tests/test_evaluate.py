from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate

if TYPE_CHECKING:
    from fastmcp import Client


async def test_evaluate_dom_query(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    js = await evaluate(client, PROFILE, "document.title")
    assert "Evaluate Test" in js


async def test_evaluate_data_attributes(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    js = await evaluate(
        client,
        PROFILE,
        "(function(){ var h = document.getElementById('data-holder'); "
        "return {user: h.dataset.user, role: h.dataset.role}; })()",
    )
    assert "Alice" in js
    assert "admin" in js


async def test_evaluate_json_block(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    js = await evaluate(
        client, PROFILE, "JSON.parse(document.getElementById('json-block').textContent)"
    )
    assert "foo" in js
    assert "bar" in js


async def test_evaluate_syntax_error(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    result = await evaluate(client, PROFILE, "{{invalid}}")
    assert "error" in result.lower()
