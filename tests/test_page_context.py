"""The "[page] <title> | <url>" line appended to actions that can navigate.

Issue #19: 91 of 8,795 evaluate calls existed only to read window.location, because
the URL is one line and a snapshot is a median of 698 characters. The line closes
that gap without a dedicated tool.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

import pytest

from camoufox_mcp.tools._page_line import _EVIDENCE_WINDOW_S, PAGE_CONTEXT_TOOLS
from tests.helpers import PROFILE, evaluate, tool_text

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
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = await _click(client, selector=".nav a")

    assert result.startswith("Clicked <a>"), result
    assert result.splitlines()[-1] == f"[page] MCP Tool Test Pages | {flask_server}/", result

    # Reported once: the next action on the same page adds nothing, because the
    # agent has already been told where it is. reload is in the set, so it would
    # carry the line if the baseline had not been updated.
    again = tool_text(await client.call_tool("reload", {"profile": PROFILE}))
    assert again == "Reloaded: MCP Tool Test Pages", again


async def test_press_key_does_not_pay_the_confirmation_cost(
    client: Client, flask_server: str
) -> None:
    """press_key is out of the set, so a keystroke never waits for a confirmation.

    The suffix spends up to ``_EVIDENCE_WINDOW_S`` proving a tab that did not move
    did not move. press_key has a 4.1 ms median over 903 real calls, 96% of them
    arrow keys inside a game loop, so paying that window on every one of them
    multiplies the cost of the tool by roughly 50 for a case where a keystroke
    rarely navigates.

    The tab has a recorded baseline here (the navigate above showed its URL), which
    is the exact condition under which the confirmation poll used to run.

    The assertion is comparative on purpose. An absolute threshold measures the machine
    as much as the code: a loaded runner makes an honest 4 ms call take 126 ms and the
    test fails for a reason that has nothing to do with the tool. So it times a tool
    that DOES pay the window on the same tab, moments apart, and requires the keystroke
    to come back clearly sooner. Both calls carry the same load, so what is left is the
    window itself.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/press-key", "profile": PROFILE})

    started = time.perf_counter()
    result = tool_text(
        await client.call_tool("press_key", {"profile": PROFILE, "key": "ArrowRight"})
    )
    keystroke = time.perf_counter() - started

    assert result == "Pressed ArrowRight", result

    # click_at is in the settling set and lands on nothing, so its whole extra cost over
    # a keystroke is the confirmation window.
    started = time.perf_counter()
    tool_text(await client.call_tool("click_at", {"profile": PROFILE, "x": 2, "y": 2}))
    confirmed = time.perf_counter() - started

    assert keystroke < confirmed - _EVIDENCE_WINDOW_S / 2, (
        f"press_key took {keystroke * 1000:.0f}ms against {confirmed * 1000:.0f}ms for a "
        f"tool that pays the {_EVIDENCE_WINDOW_S * 1000:.0f}ms window: it is paying it too"
    )


async def test_click_that_stays_put_reports_nothing(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = await _click(client, selector="#btn-single")

    assert "[page]" not in result, result
    assert "\n" not in result, result


async def test_page_line_matches_the_snapshot_header(client: Client, flask_server: str) -> None:
    """The 2 producers (this helper and the JS walk) must render the same bytes.

    They sit either side of the Python/JS boundary, so no constant can be shared and
    only a test can hold them together.
    """
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    appended = (await _click(client, selector=".nav a")).splitlines()[-1]

    snapshot = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    assert snapshot.splitlines()[0] == appended, snapshot


async def test_snapshot_is_unchanged(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/snapshot", "profile": PROFILE})

    result = tool_text(await client.call_tool("snapshot", {"profile": PROFILE}))

    assert result.startswith(f"[page] Snapshot Test | {flask_server}/snapshot"), result
    assert result.count("[page] ") == 1, result


async def test_observe_snapshot_never_duplicates_the_page_line(
    client: Client, flask_server: str
) -> None:
    """A click that stays put: 1 page line, from the observation's own header."""
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})

    result = await _click(client, selector="#btn-single", observe="snapshot")

    assert "--- observation (snapshot) ---" in result
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
    await client.call_tool("navigate", {"url": f"{flask_server}/click", "profile": PROFILE})
    await evaluate(client, PROFILE, "location.hash = 'moved'")

    failed = await _click(client, uid="e999")
    assert failed == "Error: ValueError: unknown or stale uid 'e999'; take a new snapshot", failed

    # press_key is outside the set, so it neither reports the move nor consumes it.
    quiet = tool_text(await client.call_tool("press_key", {"profile": PROFILE, "key": "Escape"}))
    assert quiet == "Pressed Escape", quiet

    recovered = await _click(client, selector="#btn-single")
    assert recovered.splitlines()[-1] == f"[page] Click Test | {flask_server}/click#moved", (
        recovered
    )
