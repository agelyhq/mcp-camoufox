"""What a tab's network listing holds across a navigation, per event interleaving.

The monitors are fed by 2 sources the browser orders only within themselves: the
document request and its sub-resources come from the browser's HTTP layer, the
navigation commit from the content process hosting the new document. A cold session's
first navigation spawns that process, so on a loaded machine the commit lands after the
page's load-time fetch has already been captured. Measured on this stack: 5 of 6 cold
navigations under CPU contention, the commit 50 to 380 ms after the fetch. On the
release runner it emptied ``list_network_requests`` for ``/infinite-scroll``, a page
whose fetch had already been answered 200.

So the interleaving is the fixture here, emitted through :class:`tests.fakes.EventTab`
rather than raced for in a browser: a test that has to win a race reports coverage it
does not have. The real-browser half of the same rule, a SUB-frame navigation retiring
nothing, is in ``test_subframe_navigation.py``.

Which document requests are the tab's own is not guesswork either: on the 152.0.4-beta.28
build a request announces the frame that asked for it, the tab's document answering with
the main frame and both a declared and a freshly injected iframe answering with a
sub-frame, all 3 under the same ``document`` resource type.

Every assertion is about the DEFAULT listing (``include_preserved`` off), because that
is the one an agent calls, and a total of 0 is what the tool renders as "No network
requests captured.".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from camoufox_mcp.sessions.page import Page
from tests.fakes import EventTab

if TYPE_CHECKING:
    from camoufox_mcp.sessions import NetworkEntry

DOC = "http://tab.test/infinite-scroll"
FETCH = "http://tab.test/api/items?page=0"
OTHER = "http://tab.test/other"
LATE = "http://tab.test/other/late.js"
EMBED = "http://tab.test/embed"


def _tab() -> tuple[EventTab, Page]:
    """A tab wired exactly as a session wires one: the Page builds the monitors."""
    events = EventTab()
    return events, Page(cast("Any", events))


def _urls(entries: list[NetworkEntry]) -> list[str]:
    return [entry.url for entry in entries]


def _status(entries: list[NetworkEntry], url: str) -> int | None:
    matched = [entry for entry in entries if entry.url == url]
    assert len(matched) == 1, f"expected {url} listed once, got {_urls(entries)}"
    return matched[0].status


def test_a_late_navigation_commit_keeps_the_new_document_s_requests() -> None:
    events, page = _tab()

    document = events.request(DOC, "document")
    events.respond(document)
    fetch = events.request(FETCH, "fetch")
    events.respond(fetch)
    # The commit for that same document, announced only now.
    events.navigated()

    live, total = page.network.list_entries()
    assert total == 1, _urls(live)
    assert _urls(live) == [FETCH]
    # Complete before it was retired, which is why the runner saw an EMPTY listing and
    # not a "pending" entry: a slow request would still have been listed.
    assert _status(live, FETCH) == 200
    # The navigation's own document request is retired with the document it replaced,
    # as it always has been: it was issued before this document existed.
    both, _ = page.network.list_entries(include_preserved=True)
    assert _urls(both) == [DOC, FETCH]


def test_a_late_commit_still_completes_a_request_it_did_not_retire() -> None:
    events, page = _tab()

    document = events.request(DOC, "document")
    events.respond(document)
    fetch = events.request(FETCH, "fetch")
    events.navigated()
    # The answer arrives after the commit. Dropping the whole pending table on a
    # rotation left this entry with nothing to complete, so it read "pending" for the
    # rest of the session even though the browser had answered it.
    events.respond(fetch, 204)

    live, _ = page.network.list_entries()
    assert _status(live, FETCH) == 204


def test_a_navigation_retires_the_previous_document_s_requests() -> None:
    events, page = _tab()

    first = events.request(OTHER, "document")
    events.respond(first)
    events.navigated()
    stale = events.request(f"{OTHER}/asset.js", "script")
    events.respond(stale)

    second = events.request(DOC, "document")
    events.respond(second)
    events.navigated()
    fetch = events.request(FETCH, "fetch")
    events.respond(fetch)

    live, total = page.network.list_entries()
    assert total == 1, _urls(live)
    assert _urls(live) == [FETCH]
    both, _ = page.network.list_entries(include_preserved=True)
    assert f"{OTHER}/asset.js" in _urls(both)


def test_a_navigation_carrying_no_document_request_retires_the_whole_ring() -> None:
    events, page = _tab()

    document = events.request(DOC, "document")
    events.respond(document)
    events.navigated()
    fetch = events.request(FETCH, "fetch")
    events.respond(fetch)

    # about:blank, a data: URL or a same-document history move: nothing in the ring can
    # belong to what the tab now shows.
    events.navigated()

    live, total = page.network.list_entries()
    assert total == 0, _urls(live)
    both, _ = page.network.list_entries(include_preserved=True)
    assert _urls(both) == [DOC, FETCH]


def test_an_embed_s_document_is_not_the_rotation_boundary() -> None:
    """The boundary is the TAB's document request, not any document request.

    Firefox announces an embed's own document under the same ``document`` resource type
    as the tab's, so a boundary taken from either lands in the MIDDLE of the current
    document's life whenever a page loads an ad slot, a captcha or a video player. The
    next commit then retires only up to that embed and leaves everything the replaced
    document asked for after it live, which is the inverse of what a rotation is for.
    """
    events, page = _tab()

    first = events.request(OTHER, "document")
    events.respond(first)
    events.navigated()
    embed = events.request(EMBED, "document", events.subframe)
    events.respond(embed)
    # Asked for by the document that is about to be replaced, after its embed loaded.
    late = events.request(LATE, "script")
    events.respond(late)

    second = events.request(DOC, "document")
    events.respond(second)
    events.navigated()
    fetch = events.request(FETCH, "fetch")
    events.respond(fetch)

    live, total = page.network.list_entries()
    assert total == 1, _urls(live)
    assert _urls(live) == [FETCH]
    both, _ = page.network.list_entries(include_preserved=True)
    assert LATE in _urls(both)


def test_a_document_request_with_no_readable_frame_is_not_the_rotation_boundary() -> None:
    """Reading a request's frame can raise, and the monitor is inside event dispatch.

    Playwright answers with an error for a service worker's request, which has no frame,
    and for a navigation request whose frame does not exist yet. Neither is the tab's own
    document, so both must read as "not the boundary", and neither may escape the
    listener: Playwright stashes what a handler raises and re-raises it on the next
    unrelated api call, which is how issue #13 turned a binary upload into a TypeError
    from another tool.
    """
    events, page = _tab()

    document = events.request(DOC, "document")
    events.respond(document)
    events.navigated()
    fetch = events.request(FETCH, "fetch")
    events.respond(fetch)
    embed = events.request_with_unreadable_frame(EMBED, "document")
    events.respond(embed)
    late = events.request(LATE, "script")
    events.respond(late)

    # No document request of the TAB's own since the rotation, so this navigation has
    # none: about:blank, a data: URL or a same-document history move, and nothing in the
    # ring can belong to what the tab now shows.
    events.navigated()

    live, total = page.network.list_entries()
    assert total == 0, _urls(live)
    both, _ = page.network.list_entries(include_preserved=True)
    assert _urls(both) == [DOC, FETCH, EMBED, LATE]


def test_an_embed_s_document_is_not_evidence_that_the_tab_navigated() -> None:
    """``last_document_reqid`` answers the settling wait in ``tools/_page_line.py``.

    A tab whose ad slot loads while a click is being answered has not moved, and a mark
    that says otherwise buys every such click the full commit budget instead of the
    evidence window.
    """
    events, page = _tab()

    events.request(DOC, "document")
    events.navigated()
    moved = page.network.last_document_reqid

    events.request(EMBED, "document", events.subframe)
    events.request_with_unreadable_frame(f"{EMBED}?round=2", "document")

    assert page.network.last_document_reqid == moved
