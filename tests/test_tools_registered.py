from __future__ import annotations

from fastmcp import Client  # noqa: TC002

from tests.helpers import tool_text

EXPECTED_TOOLS = {
    "navigate",
    "kill_session",
    "take_snapshot",
    "take_screenshot",
    "click",
    "fill",
    "press_key",
    "scroll",
    "wait_for",
    "evaluate",
    "get_content",
    "get_page_info",
    "list_network_requests",
    "get_network_request",
    "select_page",
    "new_page",
    "close_page",
    "handle_dialog",
    "upload_file",
}


async def test_all_tools_registered(client: Client) -> None:
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names), f"Missing: {EXPECTED_TOOLS - names}"


async def test_navigate_starts_session(client: Client, flask_server: str) -> None:
    result = await client.call_tool("navigate", {"url": f"{flask_server}/"})
    text = tool_text(result)
    assert "MCP Tool Test Pages" in text or "navigated" in text.lower()


async def test_navigate_bad_url(client: Client) -> None:
    result = await client.call_tool("navigate", {"url": "not-a-real-url"})
    text = tool_text(result)
    assert "error" in text.lower()


async def test_kill_session_when_none_running(client: Client) -> None:
    result = await client.call_tool("kill_session", {})
    text = tool_text(result)
    assert "no" in text.lower() or "killed" in text.lower() or "session" in text.lower()
