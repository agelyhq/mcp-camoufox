"""What ``observe`` returns when the action it follows navigates the tab.

An observation exists so the next call can act without paying for a fresh snapshot.
A tree of a document that has already been replaced is therefore worse than no tree:
every uid in it fails immediately, the result carries 2 contradictory ``[page]``
lines, and nothing in it tells the agent which one to believe.

The old regression test clicked ``#btn-single``, which cannot navigate, so it
reported coverage of this that it did not have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.tools import _settled_observation
from tests.helpers import PROFILE, evaluate, extract_uid, tool_text

if TYPE_CHECKING:
    import pytest
    from fastmcp import Client

_SNAPSHOT_MARK = "--- observation (snapshot) ---"
_TEXT_MARK = "--- observation (text) ---"

# On the index page and nowhere else, so its presence proves which document was read.
_INDEX_ONLY = "Infinite Scroll"


def _observed_tree(result: str) -> str:
    """The snapshot block an observed action appended, header included."""
    assert _SNAPSHOT_MARK in result, result
    return result.split(_SNAPSHOT_MARK, 1)[1]


async def _centre_of(client: Client, selector: str) -> tuple[float, float]:
    """Viewport centre of the first match, for the tool that takes raw coordinates."""
    raw = await evaluate(
        client,
        PROFILE,
        "(() => { const r = document.querySelector("
        f"{selector!r}"
        ").getBoundingClientRect();"
        " return Math.round(r.left + r.width / 2) + ',' + Math.round(r.top + r.height / 2); })()",
    )
    x, y = raw.strip().strip('"').split(",")
    return float(x), float(y)


async def _assert_uid_is_live(client: Client, tree: str, label: str) -> None:
    """A uid taken from an observation must address the document the agent now has."""
    uid = extract_uid(tree, label)

    read = tool_text(
        await client.call_tool("get_element", {"profile": PROFILE, "uid": uid, "prop": "text"})
    )

    assert label in read, f"uid {uid} for '{label}' does not resolve: {read}"


async def _assert_lands_on_the_index(client: Client, result: str, flask_server: str) -> None:
    assert result.count("[page] ") == 1, result
    assert f"[page] MCP Tool Test Pages | {flask_server}/" in result, result
    assert f"{flask_server}/click" not in result, result
    await _assert_uid_is_live(client, _observed_tree(result), _INDEX_ONLY)


async def test_observed_click_that_navigates_describes_the_live_page(
    client: Client, flask_server: str
) -> None:
    """The tree must be the one the click led to, named by 1 page line."""
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "click", {"profile": PROFILE, "selector": ".nav a", "observe": "snapshot"}
        )
    )

    assert result.startswith("Clicked <a>"), result
    await _assert_lands_on_the_index(client, result, flask_server)


async def test_observed_click_at_that_navigates_describes_the_live_page(
    client: Client, flask_server: str
) -> None:
    """click_at pays the same confirmation window, so it owes the same coherence.

    The snapshot first is what an agent really does, and it is load bearing here: it
    creates the element store in the document that is about to die, which is the
    state in which the observation used to read the departed document.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    await client.call_tool("snapshot", {"profile": PROFILE})
    x, y = await _centre_of(client, ".nav a")

    result = tool_text(
        await client.call_tool(
            "click_at", {"profile": PROFILE, "x": x, "y": y, "observe": "snapshot"}
        )
    )

    assert result.startswith("Clicked at"), result
    await _assert_lands_on_the_index(client, result, flask_server)


async def test_observed_fill_that_navigates_describes_the_live_page(
    client: Client, flask_server: str
) -> None:
    """A select whose change handler navigates: the jump menu plenty of sites ship."""
    await client.call_tool("navigate", {"url": f"{flask_server}/fill", "profile": PROFILE})
    await evaluate(
        client,
        PROFILE,
        "document.getElementById('select-input').addEventListener("
        "'change', () => { window.location.href = '/'; }) || 'armed'",
    )

    result = tool_text(
        await client.call_tool(
            "fill",
            {
                "profile": PROFILE,
                "selector": "#select-input",
                "value": "banana",
                "observe": "snapshot",
            },
        )
    )

    assert result.count("[page] ") == 1, result
    assert f"[page] MCP Tool Test Pages | {flask_server}/" in result, result
    await _assert_uid_is_live(client, _observed_tree(result), _INDEX_ONLY)


async def test_observed_text_of_a_navigating_click_is_the_new_page(
    client: Client, flask_server: str
) -> None:
    """The text mode carries no header of its own, so only its content betrays it."""
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = tool_text(
        await client.call_tool(
            "click", {"profile": PROFILE, "selector": ".nav a", "observe": "text"}
        )
    )

    assert _TEXT_MARK in result, result
    assert result.count("[page] ") == 1, result
    assert result.splitlines()[-1] == f"[page] MCP Tool Test Pages | {flask_server}/", result
    body = result.split(_TEXT_MARK, 1)[1]
    assert "Each page is designed to exercise" in body, result
    assert "Double-click me" not in body, result


class _RestlessTab:
    """A tab that has moved again every time a capture is read back from it.

    Mocked rather than staged in the browser: a redirect chain fast enough to move
    under 2 consecutive captures is a race, and a race makes a test that reports
    coverage it does not have, which is the very thing this file exists to correct.
    """

    def __init__(self) -> None:
        self.captures = 0
        # The 2 reporting fields the real Page carries for the settling wait.
        self.shown_url: str | None = None
        self.doc_mark: int | None = None

    @property
    def url(self) -> str:
        return f"http://tab.test/{self.captures}"

    @property
    def raw(self) -> _RestlessTab:
        return self

    async def wait_for_load_state(self, state: str, timeout: float | None = None) -> None:
        """The Playwright lifecycle wait, satisfied at once by a tab already moving."""


async def _capture(page: Any, mode: str) -> str:
    page.captures += 1
    return f"\n\n{_SNAPSHOT_MARK}\n[page] whatever it was"


async def test_a_tab_that_will_not_settle_is_named_not_described(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handing back no tree is defensible. Handing it back in silence is not."""
    tab = _RestlessTab()
    monkeypatch.setattr(_settled_observation, "observe_suffix", _capture)

    result = await _settled_observation.settled_observation(tab, "click", "snapshot")

    assert result == _settled_observation._KEPT_MOVING, result
    assert "observation skipped" in result, result
    assert "call snapshot" in result, result
    # Tried twice, then gave up: a tab in a redirect loop must not be read forever.
    assert tab.captures == 2, tab.captures


async def test_observe_none_starts_no_wait_and_no_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default must stay free: no capture, and nothing appended."""
    tab = _RestlessTab()
    monkeypatch.setattr(_settled_observation, "observe_suffix", _capture)

    assert await _settled_observation.settled_observation(tab, "click", "none") == ""
    assert tab.captures == 0, tab.captures
