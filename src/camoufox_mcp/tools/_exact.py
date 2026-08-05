"""Whole-value narrowing over the lines a search renders.

``find`` asks the page for substring matches and then keeps the ones whose name is
the requested value outright. The page is the authority on what a name is: a
rendered line is the name followed by an optional ``(attrs)`` group, and a name may
end in brackets of its own, so the line alone cannot say where the name stops. It
can say where the name starts, which is what the narrowing below leans on, and it
asks the page again whenever that is not enough.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# Re-runs the caller's own search with a different name filter and limit, and gives
# back the rendered block. Lazily evaluated, so the imports above stay type-only.
type Search = Callable[[str | None, int], Awaitable[str]]

# A rendered line, e.g. `[div[role=dialog] e3] Save (disabled)`. The tag part may
# itself contain a bracket, so the uid is what ends the prefix.
LINE = re.compile(r"^\s*\[.*?\s(e\d+)\]\s*(.*)$")
HEADER = re.compile(r"^\[found \d+/(\d+)\]")
# How many substring matches a whole-value search looks through. A whole-value match
# must not stay hidden behind the caller's own limit, and beyond this many the count
# it reports is a floor.
SCAN = 100


def split(rendered: str) -> tuple[str, list[str]]:
    """The ``[found n/m]`` header and the match lines under it."""
    header, _, body = rendered.partition("\n")
    return header, body.splitlines()


def line_rest(line: str) -> str:
    """Everything a rendered line carries after its uid: the name and its attributes."""
    match = LINE.match(line)
    return match.group(2).strip() if match else ""


def scan_was_capped(header: str, scanned: int) -> bool:
    """True when the page held more matches than the scan brought back."""
    found = HEADER.match(header)
    return found is not None and int(found.group(1)) > scanned


async def narrow(
    search: Search, lines: list[str], values: tuple[str, ...], *, scan: int
) -> list[str]:
    """The scanned lines whose name is every value, whole and case-sensitive."""
    extended: dict[str, set[str]] = {}
    kept = []
    for line in lines:
        found = LINE.match(line)
        if found is not None and await _is_whole(
            search,
            extended,
            uid=found.group(1),
            rest=found.group(2).strip(),
            values=values,
            scan=scan,
        ):
            kept.append(line)
    return kept


async def _is_whole(
    search: Search,
    extended: dict[str, set[str]],
    *,
    uid: str,
    rest: str,
    values: tuple[str, ...],
    scan: int,
) -> bool:
    """Whether this match carries every value as its whole name.

    A line that is the value outright is a match: the name starts the line and the
    page already found the value inside the name, so the two are the same string. A
    line that continues into a bracketed group is the ambiguous case, and it is
    referred back to the page rather than guessed at.
    """
    for value in values:
        if rest == value:
            continue
        if not (rest.startswith(value + " (") and rest.endswith(")")):
            return False
        if uid in await _running_past(search, extended, value, scan=scan):
            return False
    return True


async def _running_past(
    search: Search, extended: dict[str, set[str]], value: str, *, scan: int
) -> set[str]:
    """uids whose accessible name itself runs past ``value`` into a bracketed group.

    One extra read per value, cached, and only when a line is ambiguous. It keeps
    the caller's own filters and only tightens the name, so it selects a subset of
    the same scan in the same order: a uid the scan brought back is inside this
    result whenever it belongs to it, whatever the cap.
    """
    known = extended.get(value)
    if known is None:
        _, lines = split(await search(value + " (", scan))
        known = {found.group(1) for found in (LINE.match(line) for line in lines) if found}
        extended[value] = known
    return known
