from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, evaluate, open_page, tool_text
from tests.waits import poll_tool_text, poll_until, wait_predicate

if TYPE_CHECKING:
    from fastmcp import Client

COUNT_JS = "document.querySelectorAll('.item').length"
PAGE_SIZE = 10

# The path of the page itself, which the tab requested as a "document": the one entry a
# ["fetch", "xhr"] filter has to drop. No API URL on this page contains it.
PAGE_PATH = "/infinite-scroll"

# The page auto-loads while it is shorter than the viewport (``checkFillPage``), so
# "10 items are there" is not the same as "the page has stopped loading". Quiescence is
# what makes the baseline a fixed result instead of a sample of how fast the runner is.
QUIESCED_JS = f"window.isLoading === false && {COUNT_JS} >= {PAGE_SIZE}"


async def test_infinite_scroll_initial_load(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/infinite-scroll")
    await wait_predicate(client, PROFILE, f"{COUNT_JS} >= {PAGE_SIZE}")

    js = await evaluate(client, PROFILE, COUNT_JS)
    assert int(js) >= PAGE_SIZE


async def test_infinite_scroll_loads_more_on_scroll(client: Client, flask_server: str) -> None:
    """Scrolling to the bottom loads one more page of items.

    The baseline is taken once the page has gone quiet, not after a fixed second: read
    too early, ``before`` is 0 and "after > before" is then satisfied by the INITIAL
    load, so the test passes while proving nothing about scrolling. Quiesced first, and
    requiring a full extra page, only a scroll-triggered fetch can satisfy it.
    """
    await open_page(client, f"{flask_server}/infinite-scroll")
    await wait_predicate(client, PROFILE, QUIESCED_JS)

    before = int(await evaluate(client, PROFILE, COUNT_JS))
    assert before >= PAGE_SIZE

    # Scroll until the next page has landed: the count is the condition, the deadline
    # is the guardrail, and each scroll is a step towards it rather than a paced nap.
    target = before + PAGE_SIZE

    async def scroll_and_count() -> int:
        await client.call_tool("scroll", {"profile": PROFILE, "direction": "down"})
        return int(await evaluate(client, PROFILE, COUNT_JS))

    after, _ = await poll_until(scroll_and_count, lambda count: count >= target, interval=0.0)

    assert after >= target, f"scrolled from {before} items and only reached {after}"


async def test_infinite_scroll_network_requests(client: Client, flask_server: str) -> None:
    """The page's own fetch is captured, and the filter drops the page that made it.

    Polled rather than slept on. A fixed wait asserts that a 2-core runner is as fast as a
    workstation, which it is not: the page's first fetch landed well past 1 second in CI
    and the test failed for a reason unrelated to capture. The condition is unchanged, the
    deadline is simply generous enough to be about the monitor rather than the machine.

    ``/api/items`` IS a fetch, so its presence under a ``["fetch", "xhr"]`` filter said
    nothing about the filter. The document request for this very page is the entry that
    must NOT come back, and it is asserted present in the unfiltered listing first, so
    the exclusion cannot be satisfied by a listing that never held it. Both listings ask
    for ``include_preserved``: the navigation retires its own document request.
    """
    await open_page(client, f"{flask_server}/infinite-scroll")

    unfiltered = await poll_tool_text(
        client,
        "list_network_requests",
        {"profile": PROFILE, "include_preserved": True},
        "/api/items",
    )
    assert PAGE_PATH in unfiltered, unfiltered

    filtered = tool_text(
        await client.call_tool(
            "list_network_requests",
            {"profile": PROFILE, "include_preserved": True, "resource_types": ["fetch", "xhr"]},
        )
    )
    assert "/api/items" in filtered, filtered
    assert PAGE_PATH not in filtered, filtered
