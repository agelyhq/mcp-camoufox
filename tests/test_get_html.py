from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

_MARKER = "SCRIPT_MARKER_SHOULD_BE_STRIPPED"


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
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, max_chars=50)

    assert "\n[truncated " in out
    head, tail = out.split("\n[truncated ", 1)
    assert len(head) == 50
    assert tail.endswith(" chars]")
    # N reported equals the characters removed from the head.
    removed = int(tail[: -len(" chars]")])
    assert removed > 0


async def test_get_html_unlimited(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/get-html", "profile": PROFILE})

    out = await _get_html(client, max_chars=0)

    assert "[truncated" not in out
    assert "The quick brown fox jumps over the lazy dog." in out
    assert "sidebar-only-text" in out
