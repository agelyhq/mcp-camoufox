from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.helpers import BIG_TEXT_JS, PROFILE, evaluate, open_page, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

_MARKER = "SCRIPT_MARKER_SHOULD_BE_STRIPPED"

# The 5 page-owned entry points this read used to resolve at call time, replaced with
# versions that count and, for the 3 the strip pass walked, lie about what they found.
#
# `NodeList.prototype.forEach` as a no-op is the reason this test exists. It is not an
# observability leak, it is a wrong answer: the pass that removes <script> elements from
# the clone visited nothing, so the page kept its scripts in output that had asked for
# none, and nothing said so. `Document.prototype.querySelector` answering null is the
# same class of defeat one step earlier: a scope that exists reads as absent.
HOSTILE_PROTOTYPES_JS = """
(() => {
  window.__hostile =
    { querySelector: 0, querySelectorAll: 0, cloneNode: 0, forEach: 0, remove: 0 };
  const seen = (what) => { window.__hostile[what]++; };
  Document.prototype.querySelector = function () { seen('querySelector'); return null; };
  Element.prototype.querySelectorAll = function () { seen('querySelectorAll'); return []; };
  NodeList.prototype.forEach = function () { seen('forEach'); };
  Element.prototype.remove = function () { seen('remove'); };
  const clone = Node.prototype.cloneNode;
  Node.prototype.cloneNode = function (deep) { seen('cloneNode'); return clone.call(this, deep); };
  return 1;
})()
"""

# The control for the hooks above: page code calling each one, so a tally of zeros can
# only mean our calls went elsewhere. Without it, a typo in the hook names would make
# every counter stay at 0 forever and certify any implementation as clean.
CALL_THE_HOOKS_JS = """
(() => {
  document.querySelector('body');
  document.body.querySelectorAll('script');
  document.body.cloneNode(false);
  document.querySelectorAll('script').forEach(() => {});
  document.createElement('div').remove();
  return JSON.stringify(window.__hostile);
})()
"""

_NO_HOSTILE_CALLS = {
    "querySelector": 0,
    "querySelectorAll": 0,
    "cloneNode": 0,
    "forEach": 0,
    "remove": 0,
}


async def _get_html(client: Client, **kwargs: object) -> str:
    return tool_text(await client.call_tool("get_html", {"profile": PROFILE, **kwargs}))


async def test_get_html_full_document_default(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

    out = await _get_html(client)

    assert "<html" in out
    assert '<article id="main-article"' in out
    assert "The quick brown fox jumps over the lazy dog." in out
    # strip_scripts defaults to True: our marker script is gone.
    assert _MARKER not in out
    # Small document under the default cap: no truncation note.
    assert "[truncated" not in out


async def test_get_html_keep_scripts(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

    out = await _get_html(client, strip_scripts=False)

    assert _MARKER in out
    assert "<script" in out


async def test_get_html_selector_scope(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

    out = await _get_html(client, selector="#main-article")

    assert out.strip().startswith('<article id="main-article"')
    assert "The quick brown fox jumps over the lazy dog." in out
    # Scoped: nothing outside the article leaks in.
    assert "<html" not in out
    assert "sidebar-only-text" not in out
    assert "Get HTML Test" not in out


async def test_get_html_text_mode_selector(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

    out = await _get_html(client, selector="#lead", mode="text")

    assert "The quick brown fox jumps over the lazy dog." in out
    # Rendered text only, no markup.
    assert "<p" not in out
    assert "<article" not in out


async def test_get_html_no_match_selector(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

    out = await _get_html(client, selector="#does-not-exist")

    assert out == "Error: ValueError: no element matches selector '#does-not-exist'"


async def test_get_html_invalid_mode(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

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
    await open_page(client, f"{flask_server}/get-html")

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
    await open_page(client, f"{flask_server}/get-html")
    await evaluate(client, PROFILE, BIG_TEXT_JS)

    result = tool_text(
        await client.call_tool("click_at", {"profile": PROFILE, "x": 5, "y": 5, "observe": "text"})
    )

    note = result.rpartition("\n")[2]
    assert note.startswith("[truncated: showing 4000 of ")
    assert note.endswith(" chars. This cap is fixed, call get_html for the full text]")
    assert "max_chars" not in note
    assert "x" * 5000 in await _get_html(client, mode="text", max_chars=0)


async def test_strip_scripts_survives_a_page_that_owns_the_prototypes(
    client: Client, flask_server: str
) -> None:
    """A page replacing the prototypes this read walks can neither see it nor break it.

    ``strip_scripts`` was defeatable, which is worse than observable: the removal pass
    called ``NodeList.prototype.forEach``, so a page replacing it with a no-op was handed
    back its own ``<script>`` elements by a caller that had asked for none, and the answer
    looked exactly like a correct one. Everything here now goes through the boot table of
    ``dom/js/00_boot.js``.

    The snapshot before the hooks is load-bearing and not incidental: the capture happens
    when the store first runs, and the limit stated in ``docs/anti-bot.md`` is that a page
    patching BEFORE that does see us. This measures the half the capture can win, which is
    every patch installed afterwards.
    """
    await open_page(client, f"{flask_server}/get-html")
    tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    assert await evaluate(client, PROFILE, HOSTILE_PROTOTYPES_JS) == "1"

    stripped = await _get_html(client, max_chars=0)
    assert _MARKER not in stripped, "the page's own forEach decided what strip_scripts kept"
    assert '<article id="main-article"' in stripped

    # The scope is resolved through the same table: the hostile querySelector answers
    # null, so a read that went through it would report that the article does not exist.
    scoped = await _get_html(client, selector="#main-article")
    assert scoped.strip().startswith('<article id="main-article"')
    assert "The quick brown fox jumps over the lazy dog." in scoped

    assert await _get_html(client, selector="#lead", mode="text") == (
        "The quick brown fox jumps over the lazy dog."
    )

    counts = json.loads(await evaluate(client, PROFILE, "window.__hostile"))
    assert counts == _NO_HOSTILE_CALLS, f"the page counted our calls: {counts}"

    # Control: the hooks really are installed, so the zeros above are about us and not
    # about a probe that was never wired to anything.
    called = json.loads(json.loads(await evaluate(client, PROFILE, CALL_THE_HOOKS_JS)))
    assert all(hits >= 1 for hits in called.values()), called


async def test_get_html_unlimited(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/get-html")

    out = await _get_html(client, max_chars=0)

    assert "[truncated" not in out
    assert "The quick brown fox jumps over the lazy dog." in out
    assert "sidebar-only-text" in out
