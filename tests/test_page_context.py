"""The "[page] <title> | <url>" line appended to actions that can navigate.

Issue #19: 91 of 8,795 evaluate calls existed only to read window.location, because
the URL is one line and a snapshot is a median of 698 characters. The line closes
that gap without a dedicated tool.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.tools._page_line import (
    EVIDENCE_WINDOW_S,
    PAGE_CONTEXT_TOOLS,
    SETTLING_TOOLS,
)
from tests.helpers import (
    OBSERVATION_SNAPSHOT_MARK,
    PROFILE,
    RENDERED_STALE_UID,
    evaluate,
    open_page,
    tool_text,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastmcp import Client


@pytest.fixture
def redirect_url(flask_server: str) -> Iterator[str]:
    """A local endpoint that answers every GET with a 302 to the /click page.

    A real HTTP redirect, so the navigate assertions test the documented behaviour
    (the final URL is not the requested one) rather than URL canonicalisation. It
    binds port 0 so parallel test runs never collide.
    """
    target = f"{flask_server}/click"

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            """Keep the redirect server out of the pytest output."""

    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/go"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


async def _click(client: Client, **args: object) -> str:
    return tool_text(await client.call_tool("click", {"profile": PROFILE, **args}))


async def test_every_declared_tool_exists(client: Client) -> None:
    """A name the tool surface no longer has would disable the line in silence."""
    registered = {tool.name for tool in await client.list_tools()}

    assert registered >= PAGE_CONTEXT_TOOLS, PAGE_CONTEXT_TOOLS - registered


async def test_click_that_navigates_reports_the_new_page(client: Client, flask_server: str) -> None:
    """The whole point: the agent learns where the click landed, without asking."""
    await open_page(client, f"{flask_server}/click")

    result = await _click(client, selector=".nav a")

    assert result.startswith("Clicked <a>"), result
    assert result.splitlines()[-1] == f"[page] MCP Tool Test Pages | {flask_server}/", result

    # Reported once: the next action on the same page adds nothing, because the
    # agent has already been told where it is. reload is in the set, so it would
    # carry the line if the baseline had not been updated.
    again = tool_text(await client.call_tool("reload", {"profile": PROFILE}))
    assert again == "Reloaded: MCP Tool Test Pages", again


def test_press_key_is_outside_the_settling_set() -> None:
    """press_key must not be a settling tool, asserted on the set rather than on a clock.

    The cost this guards is real: confirming that a tab did not move takes up to
    EVIDENCE_WINDOW_S, and press_key has a 4.1 ms median over 903 real calls, 96% of them
    arrow keys inside a game loop, so paying it would multiply the tool's cost by roughly
    50 for a case where a keystroke rarely navigates.

    It is asserted structurally because timing cannot express it. A tool only spends the
    window when there is evidence of a navigation to settle, so on a page that stays put
    NEITHER press_key nor a settling tool waits, and the 2 measure the same thing: machine
    load. Measured under load on a static page, press_key took 218 ms against 230 ms for
    click_at, and an earlier version of this test failed on that noise while the behaviour
    was correct.

    The behavioural half, that press_key neither reports a move nor consumes it, is
    asserted end to end in test_errors_stay_one_line_and_the_move_is_reported_next.
    """
    assert "press_key" not in SETTLING_TOOLS, (
        "press_key is back in the settling set: every keystroke now waits up to "
        f"{EVIDENCE_WINDOW_S * 1000:.0f}ms to confirm a page it almost never moved"
    )
    assert "press_key" not in PAGE_CONTEXT_TOOLS, (
        "press_key would emit a [page] line, which is the same cost by another name"
    )
    # The set it is out of must not be empty, or this passes for the wrong reason.
    assert {"click", "click_at", "fill"} <= SETTLING_TOOLS, SETTLING_TOOLS


async def test_click_that_stays_put_reports_nothing(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click")

    result = await _click(client, selector="#btn-single")

    assert "[page]" not in result, result
    assert "\n" not in result, result


async def test_page_line_matches_the_snapshot_header(client: Client, flask_server: str) -> None:
    """The 2 producers (this helper and the JS walk) must render the same bytes.

    They sit either side of the Python/JS boundary, so no constant can be shared and
    only a test can hold them together.
    """
    await open_page(client, f"{flask_server}/click")
    appended = (await _click(client, selector=".nav a")).splitlines()[-1]

    snapshot = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    assert snapshot.splitlines()[0] == appended, snapshot


async def test_snapshot_is_unchanged(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/snapshot")

    result = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    assert result.startswith(f"[page] Snapshot Test | {flask_server}/snapshot"), result
    assert result.count("[page] ") == 1, result


async def test_observe_snapshot_never_duplicates_the_page_line(
    client: Client, flask_server: str
) -> None:
    """A click that stays put: 1 page line, from the observation's own header."""
    await open_page(client, f"{flask_server}/click")

    result = await _click(client, selector="#btn-single", observe="snapshot")

    assert OBSERVATION_SNAPSHOT_MARK in result
    assert result.count("[page] ") == 1, result
    assert f"[page] Click Test | {flask_server}/click" in result, result


async def test_navigate_reports_a_redirect(
    client: Client, redirect_url: str, flask_server: str
) -> None:
    result = tool_text(
        await client.call_tool("navigate", {"url": redirect_url, "profile": PROFILE})
    )

    assert result.startswith("Navigated to: Click Test"), result
    assert result.splitlines()[-1] == f"[page] Click Test | {flask_server}/click", result


async def test_navigate_without_a_redirect_reports_nothing(
    client: Client, flask_server: str
) -> None:
    result = tool_text(
        await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    )

    assert "[page]" not in result, result

    # The trailing slash a browser adds to an origin is canonicalisation, not a
    # redirect, and must not produce a line.
    origin = tool_text(
        await client.call_tool("navigate", {"url": flask_server, "profile": PROFILE})
    )
    assert origin == f"Navigated to: MCP Tool Test Pages ({flask_server}/)", origin


async def test_navigate_redirect_with_observe_snapshot_reports_once(
    client: Client, redirect_url: str, flask_server: str
) -> None:
    result = tool_text(
        await client.call_tool(
            "navigate", {"url": redirect_url, "profile": PROFILE, "observe": "snapshot"}
        )
    )

    assert result.count("[page] ") == 1, result
    assert f"[page] Click Test | {flask_server}/click" in result, result


async def test_errors_stay_one_line_and_the_move_is_reported_next(
    client: Client, flask_server: str
) -> None:
    """The one-line error contract holds even when the tab did move.

    The hash assignment moves the tab without any tool result stating it, so the
    failing click below runs on a page the agent has not been told about. The error
    must still be exactly one line, and the move must surface on the next call in
    the set that succeeds rather than being lost.
    """
    await open_page(client, f"{flask_server}/click")
    await evaluate(client, PROFILE, "location.hash = 'moved'")

    failed = await _click(client, uid="e999")
    assert failed == RENDERED_STALE_UID.format(uid="e999"), failed

    # press_key is outside the set, so it neither reports the move nor consumes it.
    quiet = tool_text(await client.call_tool("press_key", {"profile": PROFILE, "key": "Escape"}))
    assert quiet == "Pressed Escape", quiet

    recovered = await _click(client, selector="#btn-single")
    assert recovered.splitlines()[-1] == f"[page] Click Test | {flask_server}/click#moved", (
        recovered
    )
