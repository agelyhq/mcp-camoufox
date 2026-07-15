from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests.helpers import evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

EXTRACT_JS = """
(function() {
    const g = id => (document.getElementById(id) || {}).textContent || '';
    return {
        detectedOS: g('detected-os'),
        confidence: g('os-confidence'),
        score: g('score'),
        grade: g('grade'),
        errorCount: g('error-count'),
        warningCount: g('warning-count'),
        userAgent: navigator.userAgent,
        platform: navigator.platform,
    };
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


async def _run_fingerprint(client: Client, url: str, target_os: str, profile: str) -> dict:
    """Navigate to the fingerprint page, wait for FP_READY, extract results."""
    await client.call_tool(
        "navigate", {"url": url, "fingerprint_os": target_os, "profile": profile}
    )
    status = await evaluate(client, profile, WAIT_READY_JS)
    assert "ready" in status, f"Fingerprint page did not finish: {status}"
    raw = await evaluate(client, profile, EXTRACT_JS)
    return json.loads(raw)


@pytest.mark.parametrize(("target_os", "expected_os"), OS_EXPECTATIONS)
async def test_os_fingerprint(
    client: Client,
    flask_server: str,
    target_os: str,
    expected_os: str,
) -> None:
    """Fingerprint page must detect the expected OS for each fingerprint_os."""
    data = await _run_fingerprint(
        client, f"{flask_server}/fingerprint", target_os, f"fp_{target_os}"
    )

    assert data["detectedOS"] == expected_os, (
        f"Expected {expected_os!r} but detected {data['detectedOS']!r}"
    )
    assert data["userAgent"], "userAgent must not be empty"
    assert data["platform"], "platform must not be empty"


async def test_os_fingerprints_differ(client: Client, flask_server: str) -> None:
    """Each OS must produce a distinct userAgent string."""
    user_agents: dict[str, str] = {}
    for target_os, _ in OS_EXPECTATIONS:
        data = await _run_fingerprint(
            client, f"{flask_server}/fingerprint", target_os, f"ua_{target_os}"
        )
        user_agents[target_os] = data["userAgent"]

    assert len(set(user_agents.values())) == len(OS_EXPECTATIONS), (
        f"Expected {len(OS_EXPECTATIONS)} distinct UAs, got: {user_agents}"
    )


async def test_invalid_fingerprint_os(client: Client, flask_server: str) -> None:
    result = tool_text(
        await client.call_tool(
            "navigate",
            {"url": f"{flask_server}/", "profile": "bad_os", "fingerprint_os": "solaris"},
        )
    )
    assert "error" in result.lower()
    assert "fingerprint_os" in result.lower()
