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
    "go_forward",
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
    # interaction
    "click",
    "click_at",
    "hover",
    "drag",
    "fill",
    "fill_form",
    "type_text",
    "press_key",
    "scroll",
    "upload_file",
    "handle_dialog",
    # scripting
    "evaluate",
    # network / console / performance
    "list_network_requests",
    "get_network_request",
    "list_console_messages",
    "performance_summary",
}

# Names from the pre-rebuild server that must no longer be registered.
LEGACY_TOOLS = {"kill_session", "take_snapshot", "take_screenshot", "get_content", "get_page_info"}


async def test_all_tools_registered(client: Client) -> None:
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names), f"Missing: {EXPECTED_TOOLS - names}"
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
    result = await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": PROFILE})
    text = tool_text(result)
    assert "MCP Tool Test Pages" in text or "navigated" in text.lower()


async def test_navigate_bad_url(client: Client) -> None:
    result = await client.call_tool("navigate", {"url": "not-a-real-url", "profile": PROFILE})
    text = tool_text(result)
    assert "error" in text.lower()
