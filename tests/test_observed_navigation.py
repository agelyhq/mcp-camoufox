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
from tests.fakes import RestlessTab
from tests.helpers import (
    OBSERVATION_SNAPSHOT_MARK,
    OBSERVATION_TEXT_MARK,
    PROFILE,
    evaluate,
    extract_uid,
    open_page,
    tool_text,
)

if TYPE_CHECKING:
    import pytest
    from fastmcp import Client


def _observed_tree(result: str) -> str:
    """The snapshot block an observed action appended, header included."""
    assert OBSERVATION_SNAPSHOT_MARK in result, result
    return result.split(OBSERVATION_SNAPSHOT_MARK, 1)[1]


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


async def _assert_observation_matches_its_page_line(client: Client, result: str) -> None:
    """The observation must describe the page its own ``[page]`` line names, and be live.

    Asserted on the result's own content rather than on how long anything took. Which
    document wins a navigation race is a matter of milliseconds and not a promise the
    product makes: it states that the absence of the line proves nothing. What it does
    promise, and what the defect broke, is that the result never contradicts itself and
    never hands back a tree of a document that is already gone.

    So: exactly 1 page line, an observation whose title is the one that line names, and a
    uid from that observation that still resolves. All 3 are fixed facts about the string
    in hand, true on any machine at any speed.
    """
    assert result.count("[page] ") == 1, result

    tree = _observed_tree(result)
    page_line_title = result.rsplit("[page] ", 1)[1].split(" | ", 1)[0].strip()
    tree_title = tree.split("[page] ", 1)[1].split(" | ", 1)[0].strip()
    assert tree_title == page_line_title, (
        f"the observation describes {tree_title!r} while the page line says "
        f"{page_line_title!r}: the result contradicts itself\n{result}"
    )

    uid = extract_uid(tree, _first_label(tree))
    read = tool_text(
        await client.call_tool("get_element", {"profile": PROFILE, "uid": uid, "prop": "text"})
    )
    assert not read.startswith(("Error:", "Timeout:")), (
        f"uid {uid} came from the observation and no longer resolves, so the tree "
        f"belongs to a document that is gone: {read}"
    )


def _first_label(tree: str) -> str:
    """The text of the first named element in a rendered tree, whatever page it is."""
    for line in tree.splitlines():
        stripped = line.strip()
        if not stripped.startswith("[") or "]" not in stripped:
            continue
        head, _, text = stripped.partition("] ")
        if " e" in head and text.strip():
            return text.split("(")[0].strip()
    raise AssertionError(f"no named element in the observation:\n{tree}")


async def _assert_lands_on_the_index(client: Client, result: str, flask_server: str) -> None:
    assert result.count("[page] ") == 1, result
    assert f"[page] MCP Tool Test Pages | {flask_server}/" in result, result
    assert f"{flask_server}/click" not in result, result
    await _assert_observation_matches_its_page_line(client, result)


async def test_observed_click_that_navigates_describes_the_live_page(
    client: Client, flask_server: str
) -> None:
    """The tree must be the one the click led to, named by 1 page line."""
    await open_page(client, f"{flask_server}/click")

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
    await open_page(client, f"{flask_server}/click")
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
    await open_page(client, f"{flask_server}/fill")
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

    # Which document wins the race is milliseconds and not a promise. What the result
    # must never be is self-contradictory or stale, and that is a fixed fact about it.
    await _assert_observation_matches_its_page_line(client, result)


async def test_observed_text_of_a_navigating_click_is_the_new_page(
    client: Client, flask_server: str
) -> None:
    """The text mode carries no header of its own, so only its content betrays it."""
    await open_page(client, f"{flask_server}/click")

    result = tool_text(
        await client.call_tool(
            "click", {"profile": PROFILE, "selector": ".nav a", "observe": "text"}
        )
    )

    assert OBSERVATION_TEXT_MARK in result, result
    assert result.count("[page] ") == 1, result
    assert result.splitlines()[-1] == f"[page] MCP Tool Test Pages | {flask_server}/", result
    body = result.split(OBSERVATION_TEXT_MARK, 1)[1]
    assert "Each page is designed to exercise" in body, result
    assert "Double-click me" not in body, result


async def _capture(page: Any, mode: str) -> str:
    page.captures += 1
    return f"\n\n{OBSERVATION_SNAPSHOT_MARK}\n[page] whatever it was"


async def test_a_tab_that_will_not_settle_is_named_not_described(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handing back no tree is defensible. Handing it back in silence is not."""
    tab = RestlessTab()
    monkeypatch.setattr(_settled_observation, "observe_suffix", _capture)

    result = await _settled_observation.settled_observation(tab, "click", "snapshot")

    assert result == _settled_observation.KEPT_MOVING, result
    assert "observation skipped" in result, result
    assert "call snapshot" in result, result
    # Tried twice, then gave up: a tab in a redirect loop must not be read forever.
    assert tab.captures == 2, tab.captures


async def test_observe_none_starts_no_wait_and_no_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default must stay free: no capture, and nothing appended."""
    tab = RestlessTab()
    monkeypatch.setattr(_settled_observation, "observe_suffix", _capture)

    assert await _settled_observation.settled_observation(tab, "click", "none") == ""
    assert tab.captures == 0, tab.captures
