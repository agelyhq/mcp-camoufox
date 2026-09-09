"""The 2 ceilings a record lives under, and what a clipped field still says.

Both are 10,000 characters and both are measured, not guessed: the 200 that used to cap
each of them destroyed 60.4% of every `evaluate` script on disk, which is the one
argument these logs are read for. What is pinned here is that a long field survives
whole, that a giant one is cut with a suffix naming its true length, and that
``result_chars`` keeps meaning the length before anything was cut.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from camoufox_mcp.telemetry import MAX_ARG_CHARS, MAX_RESULT_CHARS
from tests.helpers import last_telemetry_record

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client


async def test_a_long_argument_survives_and_a_giant_one_is_clipped(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The 200-char cap destroyed 60.4% of the evaluate scripts it recorded.

    Both halves of the new ceiling are pinned: a script far longer than the old cap is
    on disk verbatim, and one past the new one is cut with the suffix that says how much
    was cut, so the argument that is worth reading is the one that survives.
    """
    profile = "telem_args"
    await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": profile})
    log_file = data_dir / "logs" / f"{profile}.jsonl"

    modest = "1 /*" + "x" * 5000 + "*/"
    await client.call_tool("evaluate", {"profile": profile, "script": modest})
    assert last_telemetry_record(log_file)["args"]["script"] == modest

    giant = "1 /*" + "x" * MAX_ARG_CHARS + "*/"
    await client.call_tool("evaluate", {"profile": profile, "script": giant})
    record = last_telemetry_record(log_file)
    assert record["args"]["script"] == giant[:MAX_ARG_CHARS] + f"...[{len(giant)} chars]"
    # The analytics hook measures the script the caller sent, not the clipped copy.
    assert record["script_len"] == len(giant)


async def test_a_giant_result_is_clipped_and_still_says_how_long_it_was(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    profile = "telem_big"
    await client.call_tool("navigate", {"url": f"{flask_server}/", "profile": profile})
    size = MAX_RESULT_CHARS + 5000

    await client.call_tool(
        "evaluate", {"profile": profile, "script": f"'x'.repeat({size})", "max_chars": 0}
    )

    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    note = record["result"]
    suffix = re.search(r"\.\.\.\[(\d+) chars\]$", note)
    assert suffix is not None, note
    assert len(note) == MAX_RESULT_CHARS + len(suffix.group(0))
    # result_chars keeps its meaning: the true length before anything was cut, which is
    # the same length the suffix names.
    assert record["result_chars"] == int(suffix.group(1))
    assert record["result_chars"] >= size
