from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests.helpers import evaluate, tool_text

if TYPE_CHECKING:
    from fastmcp import Client

# The 3 values the assertions below read, and nothing else: a field nobody looks at
# is a page contract this suite pretends to hold and does not.
EXTRACT_JS = """
(function() {
    return {
        detectedOS: (document.getElementById('detected-os') || {}).textContent || '',
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

# What each OS must put in ``navigator.userAgent`` and ``navigator.platform``, and by
# omission what it must NOT: the other 2 rows' tokens have to be absent from both. The
# page's ``detectedOS`` is a weighted vote (fonts 3, platform 2, webgl 2, hints 2, UA 2,
# worker 1), so a userAgent still naming the host is outvoted by the rest of the spoof
# and leaves line 1 of the assertions green. A value naming 2 systems at once is the
# same defect seen from the other side, and is what the absences below are for.
OS_TOKENS: dict[str, tuple[str, str]] = {
    "windows": ("Windows NT", "Win"),
    "linux": ("Linux", "Linux"),
    "macos": ("Mac OS X", "Mac"),
}


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
    """The page detects the requested OS, and the 2 values it can read name only that OS.

    The 2 assertions this replaced ("userAgent must not be empty", same for platform)
    could not fail: no Firefox build has an empty ``navigator.userAgent``, and an empty
    one would have failed the ``detectedOS`` comparison above it first, since the page
    votes on it. What is worth asserting is that each of those 2 values names the
    requested system ON ITS OWN, which the vote does not require, and that neither
    leaks one of the other 2 systems.
    """
    data = await _run_fingerprint(
        client, f"{flask_server}/fingerprint", target_os, f"fp_{target_os}"
    )

    assert data["detectedOS"] == expected_os, (
        f"Expected {expected_os!r} but detected {data['detectedOS']!r}"
    )
    _assert_names_only(data["userAgent"], target_os, index=0, subject="userAgent")
    _assert_names_only(data["platform"], target_os, index=1, subject="platform")


def _assert_names_only(value: str, target_os: str, *, index: int, subject: str) -> None:
    """``value`` carries ``target_os``'s token at ``index`` and no other OS's token."""
    assert OS_TOKENS[target_os][index] in value, f"{subject} {value!r} does not name {target_os}"
    for other, tokens in OS_TOKENS.items():
        if other != target_os:
            assert tokens[index] not in value, f"{subject} {value!r} also names {other}"


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
