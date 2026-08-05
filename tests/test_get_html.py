from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

_MARKER = "SCRIPT_MARKER_SHOULD_BE_STRIPPED"

# Grows the page body innerText past the 4000-char observe=text cap.
_BIG_TEXT_JS = (
    "document.body.insertAdjacentHTML('beforeend', '<p>' + 'x'.repeat(5000) + '</p>'); 'ok'"
)


async def _get_html(client: Client, **kwargs: object) -> str:
    return tool_text(await client.call_tool("get_html", {"profile": PROFILE, **kwargs}))


async def test_get_html_full_document_default(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client)

    assert "<html" in out
    assert '<article id="main-article"' in out
    assert "The quick brown fox jumps over the lazy dog." in out
    # strip_scripts defaults to True: our marker script is gone.
    assert _MARKER not in out
    # Small document under the default cap: no truncation note.
    assert "[truncated" not in out


async def test_get_html_keep_scripts(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, strip_scripts=False)

    assert _MARKER in out
    assert "<script" in out


async def test_get_html_selector_scope(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, selector="#main-article")

    assert out.strip().startswith('<article id="main-article"')
    assert "The quick brown fox jumps over the lazy dog." in out
    # Scoped: nothing outside the article leaks in.
    assert "<html" not in out
    assert "sidebar-only-text" not in out
    assert "Get HTML Test" not in out


async def test_get_html_text_mode_selector(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, selector="#lead", mode="text")

    assert "The quick brown fox jumps over the lazy dog." in out
    # Rendered text only, no markup.
    assert "<p" not in out
    assert "<article" not in out


async def test_get_html_no_match_selector(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, selector="#does-not-exist")

    assert out == "Error: ValueError: no element matches selector '#does-not-exist'"


async def test_get_html_invalid_mode(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, mode="markdown")

    assert out.startswith("Error: ValueError:")
    assert "'html'" in out
    assert "'text'" in out


async def test_get_html_truncation(client: Client, flask_server: str) -> None:
    """The note carries the exact total and names the parameter that lifts the cap.

    Both halves are load-bearing: the model sizes its follow-up request from the
    total, so an approximate total is a wrong total, and it can only act at all if
    the note names a parameter it can actually pass.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    full = await _get_html(client, max_chars=0)
    out = await _get_html(client, max_chars=50)

    head, newline, note = out.rpartition("\n")
    assert newline
    assert head == full[:50]
    assert note == f"[truncated: showing 50 of {len(full)} chars. Raise max_chars to see more]"


async def test_observation_truncation_points_at_get_html(client: Client, flask_server: str) -> None:
    """The observation cap is not a parameter, so its note must not name one.

    This scenario lives with get_html because get_html is what the note sends the
    caller to: the assertion that matters is that the advice is reachable, not that
    it is well worded, so it ends by fetching what the observation had to drop.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})
    await evaluate(client, PROFILE, _BIG_TEXT_JS)

    result = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": 5, "y": 5, "observe": "text"})
    )

    note = result.rpartition("\n")[2]
    assert note.startswith("[truncated: showing 4000 of ")
    assert note.endswith(" chars. This cap is fixed, call get_html for the full text]")
    assert "max_chars" not in note
    assert "x" * 5000 in await _get_html(client, mode="text", max_chars=0)


async def test_get_html_unlimited(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, max_chars=0)

    assert "[truncated" not in out
    assert "The quick brown fox jumps over the lazy dog." in out
    assert "sidebar-only-text" in out
