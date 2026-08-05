"""What ``observe`` costs, measured on a page big enough for the cost to matter.

An observation is an appendix to an action's result: the caller asked to click, and
gets the page back with it. It is not a deliberate capture, so it answers to a cap of
its own. Uncapped, one observed ``navigate`` on the 4,000 row page below returned
35,500 chars, more than the whole tool surface costs to send.

These tests pin that cap against the live server and the real browser, so the day the
appendix goes back to being unbounded, this fails instead of the token bill.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from camoufox_mcp.tools._observe import OBSERVE_MAX_CHARS, VALID_OBSERVE
from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

_SNAPSHOT_MARK = "--- observation (snapshot) ---"
_TEXT_MARK = "--- observation (text) ---"

# The product's one truncation note: what came back, what exists, and the next call.
_NOTE = re.compile(r"^\[truncated: showing (\d+) of (\d+) chars\. (.+)\]$")
# A rendered snapshot line, e.g. `  [button e42] Go 41`. Used to prove the cut lands
# on a line boundary: half a line carries half a uid, which reads like a usable uid.
_SNAPSHOT_LINE = re.compile(r"^\s*\[.*?\s(e\d+)\]", re.MULTILINE)
# The tools that take `observe`, and therefore must advertise its values.
_OBSERVING_TOOLS = ("click", "click_at", "fill", "navigate")
# Below this the big page is no longer big, and the cap would be untested rather
# than satisfied.
_MIN_FULL_TREE = 20000


def _block(result: str, mark: str) -> str:
    """The observation appended to a tool result, without its header.

    The snapshot walk opens its tree with the same "[page] title | url" line the
    page-context suffix uses, so 1 of them at the top is expected. A second one
    anywhere would mean the suffix landed inside the block and the parse below is
    reading something other than the tree.
    """
    head, found, block = result.partition(mark)
    assert found, f"no {mark!r} in result: {result[:400]}"
    assert head, "the observation replaced the action's own result"
    block = block.lstrip("\n")
    assert block.count("[page] ") <= 1, f"the page line appears twice: {block[:200]}"
    return block


def _split_note(block: str) -> tuple[str, re.Match[str]]:
    """The kept body and its parsed truncation note, asserting the note is there."""
    body, _, last = block.rpartition("\n")
    note = _NOTE.match(last)
    assert note is not None, f"the observation was cut with no truncation note: {last!r}"
    return body, note


async def _navigate(client: Client, url: str, observe: str) -> str:
    return tool_text(
        await client.call_tool("navigate", {"url": url, "profile": PROFILE, "observe": observe})
    )


async def test_snapshot_observation_is_capped_and_says_what_it_did(
    client: Client, flask_server: str
) -> None:
    """The appended tree is capped, cut on a line boundary, and names the way out.

    The same page is then captured deliberately with ``snapshot``, which is not
    capped in chars: the comparison is the whole point, because it proves the
    observation is an appendix rather than a second copy of the capture tool.
    """
    url = f"{flask_server}/selector-large"

    bare = await _navigate(client, url, "none")
    observed = await _navigate(client, url, "snapshot")
    block = _block(observed, _SNAPSHOT_MARK)
    body, note = _split_note(block)

    shown, total, advice = int(note.group(1)), int(note.group(2)), note.group(3)
    assert shown == len(body), f"the note claims {shown} chars, the body holds {len(body)}"
    assert total >= _MIN_FULL_TREE, f"the test page is only {total} chars; the cap is untested"
    assert advice == "This cap is fixed, call snapshot or find for the rest", advice
    assert shown <= OBSERVE_MAX_CHARS, f"{shown} chars survived a {OBSERVE_MAX_CHARS} char cap"

    # Whole lines only: the last line kept must still be a complete snapshot line.
    last_line = body.splitlines()[-1]
    assert _SNAPSHOT_LINE.match(last_line), f"the cut landed mid-line: {last_line!r}"

    full = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))
    print(
        f"navigate observe=none {len(bare)} chars, observe=snapshot {len(observed)} chars "
        f"(observation {len(block)} of {total} available), snapshot tool {len(full)} chars"
    )
    assert len(block) < len(full) / 4, "the observation is not meaningfully cheaper than snapshot"


async def test_the_last_uid_of_a_truncated_observation_still_resolves(
    client: Client, flask_server: str
) -> None:
    """A uid from the trailing edge of the cut must be a real uid, not a fragment."""
    observed = await _navigate(client, f"{flask_server}/selector-large", "snapshot")
    body, _ = _split_note(_block(observed, _SNAPSHOT_MARK))

    match = _SNAPSHOT_LINE.match(body.splitlines()[-1])
    assert match is not None
    uid = match.group(1)

    read = tool_text(
        await client.call_tool("get_element", {"profile": PROFILE, "uid": uid, "prop": "text"})
    )
    assert "Error" not in read, f"the last uid of the block did not resolve: {read}"


async def test_text_observation_is_capped_on_the_same_page(
    client: Client, flask_server: str
) -> None:
    """The text mode was already capped, and now shares the number with snapshot."""
    observed = await _navigate(client, f"{flask_server}/selector-large", "text")
    body, note = _split_note(_block(observed, _TEXT_MARK))

    assert int(note.group(1)) == len(body) == OBSERVE_MAX_CHARS
    assert int(note.group(2)) > OBSERVE_MAX_CHARS
    assert note.group(3) == "This cap is fixed, call get_html for the full text"


async def test_a_small_page_is_observed_whole(client: Client, flask_server: str) -> None:
    """The cap must not truncate an ordinary page: nothing to say, so it says nothing."""
    observed = await _navigate(client, f"{flask_server}/click", "snapshot")
    block = _block(observed, _SNAPSHOT_MARK)

    assert "[truncated" not in block, block[-300:]
    assert _SNAPSHOT_LINE.search(block), "the observation carries no uid line at all"
    assert len(block) < OBSERVE_MAX_CHARS


async def test_observe_advertises_its_values_in_the_schema(client: Client) -> None:
    """The valid modes are machine-readable, not prose a client may never show.

    The instructions are optional for a client to render, so an agent can meet
    ``observe`` with no idea what it accepts. The enum costs 34 chars per tool and
    removes the guess. Validation stays ours, so a wrong value still returns the
    product's one-line error rather than a framework validation dump.
    """
    schemas = {tool.name: tool.inputSchema for tool in await client.list_tools()}
    for name in _OBSERVING_TOOLS:
        observe = schemas[name]["properties"]["observe"]
        assert observe["enum"] == list(VALID_OBSERVE), f"{name}: {observe}"
        assert observe["default"] == "none", f"{name}: {observe}"
