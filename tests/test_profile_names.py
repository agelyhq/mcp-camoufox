from __future__ import annotations

import json
from typing import TYPE_CHECKING

from camoufox_mcp.profile_name import is_valid_profile
from tests.helpers import tool_text

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client

# Names that must never reach the filesystem. Every one was measured against the
# pre-fix code: the traversal and absolute cases wrote real files OUTSIDE the data
# root, ".." resolved to the data root itself, "" collided with the _server telemetry
# bucket, and the newline case is the one a real logged call actually created.
HOSTILE = {
    "traversal": "../../pwned",
    "traversal_deep": "../" * 6 + "pwned-deep",
    "traversal_inline": "ok/../../pwned-inline",
    "empty": "",
    "dot": ".",
    "dotdot": "..",
    "dotdotdot": "...",
    "newline": 'qa-portal">\n',
    "nul": "qa\x00portal",
    "overlong": "x" * 300,
    "leading_dot": ".hidden-pwned",
    "server_bucket": "_server",
    "space": "qa pwned",
    "slash_only": "/",
}

# Shapes present in this machine's real profiles directory today, plus the exact
# length boundary. Rejecting any of these would strand a signed-in profile on disk.
LEGIT = (
    "alice5",
    "broodz-qa-320",
    "verify-b-you-bouygues-telecom-",
    "qa.portal",
    "a_b",
    "9lives",
    "x",
    "y" * 64,
)

# Substrings only a successful traversal could put on disk.
_STRAY_MARKERS = ("pwned", "portal", "hidden")


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")} if root.exists() else set()


def _strays(tmp_path: Path) -> list[str]:
    return sorted(str(p) for p in tmp_path.rglob("*") if any(m in p.name for m in _STRAY_MARKERS))


async def test_hostile_profile_names_are_rejected_before_touching_disk(
    client: Client, tmp_path: Path, data_dir: Path
) -> None:
    """navigate must refuse an unsafe profile name and create nothing for it."""
    for case, profile in HOSTILE.items():
        result = tool_text(
            await client.call_tool("navigate", {"url": "about:blank", "profile": profile})
        )
        assert result.startswith("Error: InvalidProfileNameError: "), f"{case}: {result!r}"
        # The error contract is one line and states what IS allowed.
        assert "\n" not in result, f"{case}: error spans several lines"
        assert "is not a valid name" in result, f"{case}: {result!r}"
        assert "letters, digits" in result and "1 to 64" in result, f"{case}: {result!r}"
        # A 300-char name must not blow the message up: it stays under the 200-char
        # telemetry note cap, so the error is never logged truncated either.
        assert len(result) <= 200, f"{case}: error is {len(result)} chars"

    # No profile directory and no lock file was created for any of them, and nothing
    # escaped the data root (../../pwned would land directly in tmp_path).
    assert _tree(data_dir / "profiles") == set()
    assert _strays(tmp_path) == []


async def test_hostile_profile_names_never_create_a_log_file(
    client: Client, tmp_path: Path, data_dir: Path
) -> None:
    """Every rejected call is still logged, in the server bucket, under its true name."""
    for profile in HOSTILE.values():
        await client.call_tool("navigate", {"url": "about:blank", "profile": profile})

    logs = data_dir / "logs"
    jsonl = sorted(p.name for p in logs.glob("*.jsonl"))
    assert jsonl == ["_server.jsonl"], f"unsafe names created log files: {jsonl}"
    assert _strays(tmp_path) == []

    records = [
        json.loads(line)
        for line in (logs / "_server.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    logged = {r["profile"] for r in records if r["tool"] == "navigate"}
    # The record keeps the name the agent actually asked for: rerouting the FILE must
    # not lose the evidence of what was requested.
    for profile in HOSTILE.values():
        assert profile in logged, f"no telemetry record for {profile!r}"


async def test_legit_profile_name_still_launches_and_logs(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """A dotted/underscored/hyphenated name must still get a session and its own log."""
    profile = "qa.name_check-1"
    result = tool_text(
        await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": profile})
    )
    assert result.startswith("Navigated to:"), result
    assert (data_dir / "profiles" / profile).is_dir()
    assert (data_dir / "logs" / f"{profile}.jsonl").exists()

    assert all(is_valid_profile(p) for p in LEGIT)
    assert not any(is_valid_profile(p) for p in HOSTILE.values())
    assert not is_valid_profile("z" * 65), "the length cap must reject 65 characters"
