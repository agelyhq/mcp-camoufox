from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

from camoufox_mcp.tools import (
    click,
    close_page,
    evaluate,
    fill,
    get_content,
    get_network_request,
    get_page_info,
    handle_dialog,
    kill_session,
    list_console_messages,
    list_network_requests,
    list_profiles,
    navigate,
    new_page,
    press_key,
    scroll,
    select_page,
    take_screenshot,
    take_snapshot,
    upload_file,
    wait_for,
)

_TOOL_MODULES = [
    navigate,
    kill_session,
    take_snapshot,
    take_screenshot,
    click,
    fill,
    press_key,
    scroll,
    wait_for,
    evaluate,
    get_content,
    get_page_info,
    list_console_messages,
    list_network_requests,
    get_network_request,
    select_page,
    new_page,
    close_page,
    handle_dialog,
    upload_file,
    list_profiles,
]


def register_all_tools(mcp: FastMCP) -> None:
    for module in _TOOL_MODULES:
        module.register(mcp)
