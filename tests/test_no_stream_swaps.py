"""This process never assigns ``sys.stdout`` or ``sys.stderr``: the source is read to prove it.

A swap of the process streams is process-global whichever thread performs it, and the
stdio transport reads ``sys.stdout`` when it starts: fastmcp 4 suspends between our
lifespan's ``yield`` and that read, and a background refresh that redirected the streams
from a worker thread in that window handed mcp a ``StringIO``, an ``AttributeError`` on
``.buffer``, and a host reporting "Connection closed" on every start. The fetches now
run in a child process (``updater/child.py``); this test keeps the swap from coming back
anywhere under ``src/``, in any spelling ``contextlib`` or a bare assignment offers.

The single exemption is ``sessions/quiet.py``, kept because camoufox's launch thread
prints with bare ``print`` and rich against the live streams and offers no other sink,
and safe because a session can only be created by a tool call, which can only arrive
over a transport that already holds its own handle on fd 1. The file states that
invariant; this test states the exemption, so the 2 cannot drift apart silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "camoufox_mcp"

# Every spelling of a process-global stream swap. Plain substrings, matched on the
# source text, so a redirect hidden in a helper or an alias still has to name one of
# these at the point it happens.
FORBIDDEN = (
    "redirect_stdout",
    "redirect_stderr",
    "sys.stdout =",
    "sys.stderr =",
    "sys.__stdout__ =",
)

# The one file allowed to swap the streams, and why, in the sentence its docstring must
# keep: the exemption is earned by the invariant, not by the filename.
EXEMPT = Path("sessions") / "quiet.py"
EXEMPTION_REASON = "the stdio transport claims fd 1 before"


def _source_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, f"no sources under {SRC}"
    return files


def _hits(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if any(f in line for f in FORBIDDEN)]


def test_no_source_file_swaps_the_process_streams() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _source_files():
        if path.relative_to(SRC) == EXEMPT:
            continue
        hits = _hits(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(SRC))] = hits
    assert offenders == {}, (
        "a process-global stream swap is back; run the fetch in a child process "
        f"(updater/child.py) instead: {offenders}"
    )


def test_the_exemption_is_the_one_documented() -> None:
    """Control for the guard: the exempt file really swaps, and says what makes it safe.

    A guard whose exemption names a file that no longer swaps is a guard nobody
    re-reads; and an exemption without its invariant is a hole, not a decision.
    """
    text = (SRC / EXEMPT).read_text(encoding="utf-8")
    assert _hits(text), f"{EXEMPT} no longer swaps the streams: drop the exemption"
    assert EXEMPTION_REASON in text, f"{EXEMPT} must state the invariant that makes it safe"


@pytest.mark.parametrize(
    "line",
    [
        "with contextlib.redirect_stdout(io.StringIO()):",
        "with redirect_stderr(sink):",
        "sys.stdout = sys.stderr = io.StringIO()",
        "    sys.stderr = open(os.devnull, 'w')",
        "sys.__stdout__ = sink",
    ],
)
def test_the_probe_detects_each_spelling(line: str) -> None:
    """Control: each forbidden spelling is caught before its absence is asserted."""
    assert _hits(line) == [line.strip()]
