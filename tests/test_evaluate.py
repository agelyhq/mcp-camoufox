from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text


async def test_evaluate_dom_query(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate"})

    js = tool_text(await client.call_tool("evaluate", {"script": "document.title"}))
    assert "Evaluate Test" in js


async def test_evaluate_data_attributes(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {
                "script": "(function(){ var h = document.getElementById('data-holder'); "
                "return {user: h.dataset.user, role: h.dataset.role}; })()"
            },
        )
    )
    assert "Alice" in js
    assert "admin" in js


async def test_evaluate_json_block(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate"})

    js = tool_text(
        await client.call_tool(
            "evaluate",
            {"script": "JSON.parse(document.getElementById('json-block').textContent)"},
        )
    )
    assert "foo" in js
    assert "bar" in js


async def test_evaluate_syntax_error(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate"})

    result = tool_text(await client.call_tool("evaluate", {"script": "{{invalid}}"}))
    assert "error" in result.lower()
