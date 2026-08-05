from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

EXPECTED_TOOLS = {
    # session
    "list_sessions",
    "close_session",
    # navigation
    "navigate",
    "reload",
    "go_back",
    "wait_for",
    # tabs
    "list_pages",
    "new_page",
    "close_page",
    "select_page",
    # inspection
    "snapshot",
    "screenshot",
    "get_html",
    "find",
    "get_element",
    # interaction
    "click",
    "click_at",
    "fill",
    "fill_form",
    "press_key",
    "scroll",
    "upload_file",
    "handle_dialog",
    # scripting
    "evaluate",
    # network / console
    "list_network_requests",
    "get_network_request",
    "list_console_messages",
}

# Names that must no longer be registered: the pre-rebuild server's tools, plus the 5
# retired in v0.3.0 after telemetry measured them unused (see docs/CHANGELOG.md).
LEGACY_TOOLS = {
    "kill_session",
    "take_snapshot",
    "take_screenshot",
    "get_content",
    "get_page_info",
    "drag",
    "go_forward",
    "hover",
    "performance_summary",
    "type_text",
}


async def test_all_tools_registered(client: Client) -> None:
    """The registered set is exactly EXPECTED_TOOLS, not merely a superset.

    A subset check lets an unlisted tool ship unnoticed, and the payload budget is
    measured per tool, so every addition has to be declared here on purpose.
    """
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, (
        f"Missing: {EXPECTED_TOOLS - names}; unexpected: {names - EXPECTED_TOOLS}"
    )
    assert not (LEGACY_TOOLS & names), f"Legacy tools still present: {LEGACY_TOOLS & names}"


async def test_every_tool_requires_profile(client: Client) -> None:
    """Every tool except the profile-less `list_sessions` must expose a `profile` arg."""
    tools = await client.list_tools()
    for t in tools:
        props = (t.inputSchema or {}).get("properties", {})
        if t.name == "list_sessions":
            assert "profile" not in props
        else:
            assert "profile" in props, f"{t.name} is missing the profile argument"


async def test_navigate_starts_session(client: Client, flask_server: str) -> None:
    """The first call for a profile launches a browser and reports the landed URL.

    The old `"MCP Tool Test Pages" in text or "navigated" in text.lower()` could not
    fail on the first branch: navigate never returns page content, and its success
    string always contains "Navigated", so the disjunction only ever tested that the
    call did not error.
    """
    result = await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": PROFILE})
    text = tool_text(result)
    assert text == f"Navigated to: MCP Tool Test Pages ({flask_server}/)", text

    listing = tool_text(await client.call_tool("list_sessions", {}))
    assert f"Session '{PROFILE}'" in listing, listing


async def test_navigate_bad_url(client: Client) -> None:
    result = await client.call_tool("navigate", {"url": "not-a-real-url", "profile": PROFILE})
    text = tool_text(result)
    assert "error" in text.lower()
