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


async def test_evaluate_async_iife(client: Client, flask_server: str) -> None:
    """The documented async pattern: wrap awaits in an async IIFE that returns a value."""
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    js = await evaluate(
        client,
        PROFILE,
        "(async () => { const r = await fetch('/api/data'); return r.json(); })()",
    )
    assert "Alpha" in js
    assert "Beta" in js
    assert "error" not in js.lower()


async def test_evaluate_bare_promise(client: Client, flask_server: str) -> None:
    """A bare Promise-returning expression is awaited automatically before serialization."""
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    js = await evaluate(client, PROFILE, "fetch('/api/data').then(r => r.json())")
    assert "Gamma" in js
    assert "error" not in js.lower()


async def test_evaluate_top_level_await_rejected(client: Client, flask_server: str) -> None:
    """Regression: a bare top-level ``await`` is a SyntaxError — the async-IIFE footgun.

    The script is eval'd as a plain expression (not a module), so top-level await
    is invalid. The docstring steers callers to the async-IIFE / bare-Promise forms
    instead; this locks in the failure so the guidance never silently rots.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    result = await evaluate(client, PROFILE, "await fetch('/api/data').then(r => r.json())")
    assert "error" in result.lower()
    assert "await" in result.lower()
