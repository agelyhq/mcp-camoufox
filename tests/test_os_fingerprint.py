from __future__ import annotations

import json

import pytest
from fastmcp import Client

from camoufox_mcp.server import mcp
from tests.helpers import tool_text

EXTRACT_JS = """
(function() {
    const g = id => (document.getElementById(id) || {}).textContent || '';
    return JSON.stringify({
        detectedOS: g('detected-os'),
        confidence: g('os-confidence'),
        score: g('score'),
        grade: g('grade'),
        errorCount: g('error-count'),
        warningCount: g('warning-count'),
        userAgent: navigator.userAgent,
        platform: navigator.platform,
    });
})()
"""

WAIT_READY_JS = """
(async () => {
    for (let i = 0; i < 100; i++) {
        if (document.title === 'FP_READY') return 'ready';
        await new Promise(r => setTimeout(r, 100));
    }
    return 'timeout';
})()
"""

OS_EXPECTATIONS: list[tuple[str, str]] = [
    ("windows", "Windows"),
    ("linux", "Linux"),
    ("macos", "macOS"),
]


async def _run_fingerprint(c: Client, url: str, target_os: str) -> dict:
    """Navigate to the fingerprint page, wait for FP_READY, extract results."""
    await c.call_tool("navigate", {"url": url, "target_os": target_os})
    status = tool_text(await c.call_tool("evaluate", {"script": WAIT_READY_JS}))
    assert status == "ready", f"Fingerprint page did not finish: {status}"
    raw = tool_text(await c.call_tool("evaluate", {"script": EXTRACT_JS}))
    return json.loads(raw)


@pytest.mark.parametrize(("target_os", "expected_os"), OS_EXPECTATIONS)
async def test_os_fingerprint(
    flask_server: str,
    target_os: str,
    expected_os: str,
) -> None:
    """Fingerprint page must detect the expected OS for each target_os."""
    async with Client(mcp) as c:
        data = await _run_fingerprint(c, f"{flask_server}/fingerprint", target_os)

        assert data["detectedOS"] == expected_os, (
            f"Expected {expected_os!r} but detected {data['detectedOS']!r}"
        )
        assert data["userAgent"], "userAgent must not be empty"
        assert data["platform"], "platform must not be empty"

        await c.call_tool("kill_session", {})


async def test_os_fingerprints_differ(flask_server: str) -> None:
    """Each OS must produce a distinct userAgent string."""
    user_agents: dict[str, str] = {}
    for target_os, _ in OS_EXPECTATIONS:
        async with Client(mcp) as c:
            data = await _run_fingerprint(c, f"{flask_server}/fingerprint", target_os)
            user_agents[target_os] = data["userAgent"]
            await c.call_tool("kill_session", {})

    assert len(set(user_agents.values())) == len(OS_EXPECTATIONS), (
        f"Expected {len(OS_EXPECTATIONS)} distinct UAs, got: {user_agents}"
    )
