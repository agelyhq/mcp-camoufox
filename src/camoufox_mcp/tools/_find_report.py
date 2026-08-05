"""What ``find`` says when it found nothing.

A dead end an agent cannot act on costs it a whole turn, so the report names what the
page did contain. English is the product's output language, which is why the plural
rules and the phrasing table live here rather than inside the search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from camoufox_mcp.dom import find_elements
from camoufox_mcp.tools._exact import HEADER, line_rest, split

if TYPE_CHECKING:
    from camoufox_mcp.dom import RegistryPage

# How many names a not-found report lists before it trails off.
_NAMES_LISTED = 5

_PHRASES = {
    "name": 'named{exactly} "{value}"',
    "label": 'labelled{exactly} "{value}"',
    "text": 'with{exactly} the text "{value}"',
    "placeholder": 'with{exactly} the placeholder "{value}"',
    "test_id": 'with the test id "{value}"',
    "css": 'matching "{value}"',
}

Criteria = tuple[tuple[str, str], ...]


async def report_nothing(
    page: RegistryPage, *, role: str | None, exact: bool, criteria: Criteria
) -> str:
    """Say what the query did see, so the next call can be right instead of blind.

    One extra read buys the names the role actually carries, which turns a dead end
    into a fixable typo. It is only worth it when a criterion other than the role can
    be at fault: a role that matches nothing is already the whole answer.
    """
    if role and len(criteria) > 1:
        header, lines = split(await find_elements(page, role=role, limit=_NAMES_LISTED))
        if lines:
            return _role_report(role, exact, criteria, header, lines)
    note = " (whole value, case-sensitive)" if exact else ""
    return f"no element matches {criteria_text(criteria)}{note}"


def _role_report(role: str, exact: bool, criteria: Criteria, header: str, lines: list[str]) -> str:
    names = [line_rest(line) or "(no name)" for line in lines]
    found = HEADER.match(header)
    total = int(found.group(1)) if found else len(names)
    listed = ", ".join(f'"{name}"' for name in names)
    if total > len(names):
        listed += ", ..."
    subject = _subject(exact, criteria)
    return f"no {role} {subject}. {total} {_plural(role, total)} found, named: {listed}"


def _subject(exact: bool, criteria: Criteria) -> str:
    """How the criteria other than the role read in a sentence."""
    rest = [(field, value) for field, value in criteria if field != "role"]
    exactly = " exactly" if exact else ""
    if len(rest) == 1:
        field, value = rest[0]
        return _PHRASES[field].format(value=value, exactly=exactly)
    return f"matching{exactly} {criteria_text(rest)}"


def criteria_text(criteria: Criteria | list[tuple[str, str]]) -> str:
    return ", ".join(f'{field} "{value}"' for field, value in criteria)


def _plural(role: str, count: int) -> str:
    if count == 1:
        return role
    return role + ("es" if role.endswith(("s", "x", "z", "ch", "sh")) else "s")
