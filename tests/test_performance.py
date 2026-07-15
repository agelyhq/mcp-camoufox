from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import PROFILE, tool_text

if TYPE_CHECKING:
    from fastmcp import Client


async def test_performance_summary_shape(client: Client, flask_server: str) -> None:
    await client.call_tool("navigate", {"url": f"{flask_server}/network", "profile": PROFILE})

    result = tool_text(await client.call_tool("performance_summary", {"profile": PROFILE}))

    assert "Performance summary for" in result
    assert "/network" in result
    assert "Navigation timings:" in result
    # Real navigation entry exists, so a concrete phase timing must be reported.
    assert "Time to first byte" in result
    assert "ms" in result
    assert "Resources loaded:" in result
    assert "Total transfer size:" in result
