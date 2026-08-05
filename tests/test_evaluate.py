from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests.helpers import PROFILE, evaluate, extract_uid, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# One object far past the default character cap: the only cut available to it is a
# character boundary, which cannot leave a parseable document.
_BIG_OBJECT_JS = "({label: 'report', body: 'z'.repeat(50000)})"
# 40 padded objects: under max_items, so a lowered max_items is what binds, and the
# cut lands on an element boundary.
_PADDED_ARRAY_JS = "Array.from({length: 40}, (_, i) => ({i: i, pad: 'ab'.repeat(60)}))"


async def _capped(client: Client, script: str, **caps: int) -> str:
    return tool_text(
        await client.call_tool("evaluate", {"profile": PROFILE, "script": script, **caps})
    )


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


async def test_evaluate_oversized_object_is_reported_as_a_fragment(
    client: Client, flask_server: str
) -> None:
    """An object caps on serialised length, so what comes back does not parse.

    The note has to say that outright. Told only that something was truncated, a
    caller hands the text to a parser, gets a decode error with no explanation, and
    has no reason to connect it to the cap it could have raised.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    full = await _capped(client, _BIG_OBJECT_JS, max_chars=0)
    result = await evaluate(client, PROFILE, _BIG_OBJECT_JS)

    body, _, note = result.rpartition("\n")
    assert json.loads(full)["label"] == "report"
    assert len(body) == 20000
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)
    assert note == (
        f"[truncated: showing 20000 of {len(full)} chars. Cut mid-value, so this is "
        "a fragment and not valid JSON. Raise max_chars to see more]"
    )


async def test_evaluate_truncated_array_stays_parseable(client: Client, flask_server: str) -> None:
    """The array path cuts on an element boundary, so no fragment warning applies."""
    await client.call_tool("navigate", {"url": f"{flask_server}/evaluate", "profile": PROFILE})

    result = await _capped(client, _PADDED_ARRAY_JS, max_items=6)

    body, _, note = result.rpartition("\n")
    assert [item["i"] for item in json.loads(body)] == [0, 1, 2, 3, 4, 5]
    assert note == "[truncated: showing 6 of 40 items. Raise max_items to see more]"


async def _uids(client: Client, flask_server: str, *labels: str) -> list[str]:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    snap = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    return [extract_uid(snap, label) for label in labels]


async def _evaluate_uids(client: Client, script: str, uids: list[str]) -> str:
    return tool_text(
        await client.call_tool("evaluate", {"profile": PROFILE, "script": script, "uids": uids})
    )


async def test_evaluate_with_two_uids(client: Client, flask_server: str) -> None:
    """The documented (a, b) => ... form: elements arrive as separate arguments."""
    first, second = await _uids(client, flask_server, "Click me", "Count clicks")

    result = await _evaluate_uids(
        client, "(a, b) => a.textContent.trim() + '|' + b.textContent.trim()", [first, second]
    )

    assert result == '"Click me|Count clicks"'


async def test_evaluate_uids_receives_live_nodes(client: Client, flask_server: str) -> None:
    (uid,) = await _uids(client, flask_server, "Click me")

    result = await _evaluate_uids(
        client, "(el) => { el.textContent = 'Rewritten'; return el.tagName; }", [uid]
    )

    assert result == '"BUTTON"'
    assert "Rewritten" in await evaluate(
        client, PROFILE, "document.getElementById('btn-single').textContent"
    )


async def test_evaluate_uids_stale(client: Client, flask_server: str) -> None:
    (uid,) = await _uids(client, flask_server, "Click me")
    await evaluate(client, PROFILE, "document.getElementById('btn-single').remove()")

    result = await _evaluate_uids(client, "(el) => el.tagName", [uid])

    assert result == f"Error: ValueError: unknown or stale uid '{uid}'; take a new snapshot"


async def test_evaluate_uids_syntax_error_hides_the_wrapper(
    client: Client, flask_server: str
) -> None:
    """The caller must never read the name of a wrapper it did not write."""
    (uid,) = await _uids(client, flask_server, "Click me")

    result = await _evaluate_uids(client, "(a =>", [uid])

    assert "script is not a valid function expression" in result
    for leak in ("store", "ids", "apply", "@debugger eval code"):
        assert leak not in result, result


async def test_evaluate_uids_non_function(client: Client, flask_server: str) -> None:
    (uid,) = await _uids(client, flask_server, "Click me")

    result = await _evaluate_uids(client, "42", [uid])

    assert "script must be a function expression" in result


async def test_evaluate_uids_async(client: Client, flask_server: str) -> None:
    """A promise the caller's own script returns is awaited inside the envelope."""
    (uid,) = await _uids(client, flask_server, "Click me")

    result = await _evaluate_uids(
        client,
        "async (el) => { await new Promise(r => setTimeout(r, 50)); return el.tagName; }",
        [uid],
    )

    assert result == '"BUTTON"'


async def test_evaluate_uids_runs_once(client: Client, flask_server: str) -> None:
    """No retry path may ever double-execute a script with side effects."""
    (uid,) = await _uids(client, flask_server, "Click me")
    await evaluate(client, PROFILE, "window.__n = 0")

    await _evaluate_uids(client, "(el) => { window.__n += 1; return window.__n; }", [uid])

    assert await evaluate(client, PROFILE, "window.__n") == "1"


async def test_evaluate_uids_rejects_unsupported_uid(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = await _evaluate_uids(client, "(el) => el.tagName", ["not-a-uid"])

    assert result == "Error: ValueError: unknown or stale uid 'not-a-uid'; take a new snapshot"


async def test_evaluate_uids_unused_by_the_script(client: Client, flask_server: str) -> None:
    """Passing uids to a script that ignores them is not an error."""
    (uid,) = await _uids(client, flask_server, "Click me")

    assert await _evaluate_uids(client, "() => 42", [uid]) == "42"
