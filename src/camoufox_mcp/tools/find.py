from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from camoufox_mcp.dom import find_elements
from camoufox_mcp.tools._base import get_page, get_session, tool
from camoufox_mcp.tools._exact import SCAN, narrow, scan_was_capped, split
from camoufox_mcp.tools._find_report import report_nothing

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.dom import RegistryPage
    from camoufox_mcp.tools._base import ToolDeps
    from camoufox_mcp.tools._exact import Search

# What `label` searches: form controls, editable hosts, and anything that names
# itself through ARIA. Without it a label lookup also returns every container that
# repeats the field's text, which is never what the caller meant.
_LABELLED = (
    "input, select, textarea, button, "
    '[contenteditable=""], [contenteditable="true"], [aria-label], [aria-labelledby]'
)
_FIELDS = ("role", "name", "text", "label", "placeholder", "test_id", "css")
_ATTRIBUTES = (("placeholder", "placeholder"), ("test_id", "data-testid"))


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def find(
        profile: str,
        role: str | None = None,
        name: str | None = None,
        text: str | None = None,
        label: str | None = None,
        placeholder: str | None = None,
        test_id: str | None = None,
        css: str | None = None,
        exact: bool = False,
        limit: int = 5,
    ) -> str:
        """Find a few elements by role, name, text, label, placeholder, test id or CSS.

        Read-only, with the lines and uids ``snapshot`` gives. At least 1 filter is
        required and every filter given must hold. Give only 1 of css, label and
        placeholder/test_id, and only 1 of name and label.

        Args:
            role: Exact ARIA role, explicit or implicit: button, link, textbox,
                checkbox, combobox, heading.
            name: Accessible name (aria-label, bound label, or text).
            text: The element's own text.
            label: Like name, but only over form controls and ARIA-labelled elements.
            exact: Whole values, case-sensitive, instead of substrings.
            limit: Matches rendered; the header carries the total found.
        """
        query = _build_query(
            role=role,
            name=name,
            text=text,
            label=label,
            placeholder=placeholder,
            test_id=test_id,
            css=css,
            exact=exact,
        )
        session = await get_session(deps, profile)
        page = get_page(session)
        return await _search(page, query, limit=limit)


@dataclass(frozen=True)
class _Query:
    """One search: the filter slots the page understands, plus what to report."""

    role: str | None
    name: str | None
    text: str | None
    css: str | None
    exact: bool
    # The values a whole-value comparison must find in the rendered name; empty
    # whenever the page-side match is already exact enough on its own.
    exact_names: tuple[str, ...]
    # Every filter as the caller gave it, in signature order, for the messages.
    criteria: tuple[tuple[str, str], ...]


async def _search(page: RegistryPage, query: _Query, *, limit: int) -> str:
    search = _searcher(page, query)
    if not query.exact_names:
        header, lines = split(await search(query.name, limit))
        if not lines:
            raise ValueError(await _nothing(page, query))
        return "\n".join([header, *lines])

    scan = max(limit, SCAN)
    scanned_header, scanned = split(await search(query.name, scan))
    kept = await narrow(search, scanned, query.exact_names, scan=scan)
    lines = kept[:limit]
    if not lines:
        raise ValueError(await _nothing(page, query))
    # The count is drawn from the scan, so a scan that hit its own cap can only give
    # a floor. A total an agent cannot trust is worse than one it knows is partial.
    floor = "+" if scan_was_capped(scanned_header, len(scanned)) else ""
    return "\n".join([f"[found {len(lines)}/{len(kept)}{floor}]", *lines])


def _searcher(page: RegistryPage, query: _Query) -> Search:
    """The caller's query with its name filter left open, ready to be re-run."""

    async def search(name: str | None, limit: int) -> str:
        return await find_elements(
            page, role=query.role, name=name, text=query.text, css=query.css, limit=limit
        )

    return search


async def _nothing(page: RegistryPage, query: _Query) -> str:
    """The not-found report for this query, phrased by ``_find_report``."""
    return await report_nothing(page, role=query.role, exact=query.exact, criteria=query.criteria)


def _build_query(
    *,
    role: str | None,
    name: str | None,
    text: str | None,
    label: str | None,
    placeholder: str | None,
    test_id: str | None,
    css: str | None,
    exact: bool,
) -> _Query:
    given = {
        "role": role,
        "name": name,
        "text": text,
        "label": label,
        "placeholder": placeholder,
        "test_id": test_id,
        "css": css,
    }
    criteria = tuple(
        (field, given[field].strip()) for field in _FIELDS if given[field] and given[field].strip()
    )
    values = dict(criteria)
    if not values:
        raise ValueError(
            "find needs at least one of role, name, text, label, placeholder, test_id or css"
        )
    if "name" in values and "label" in values:
        raise ValueError("name and label both match the accessible name; give only one")
    exact_names = (
        tuple(_collapse(values[field]) for field in ("name", "label", "text") if field in values)
        if exact
        else ()
    )
    role_value = values.get("role")
    return _Query(
        role=role_value.lower() if role_value else None,
        name=values.get("name") or values.get("label"),
        text=values.get("text"),
        css=_candidates(values, exact=exact),
        exact=exact,
        exact_names=exact_names,
        criteria=criteria,
    )


def _candidates(values: dict[str, str], *, exact: bool) -> str | None:
    """The CSS that narrows the candidate set, from css, label, placeholder or test_id."""
    attributes = [
        _attribute(attribute, values[field], exact=exact)
        for field, attribute in _ATTRIBUTES
        if field in values
    ]
    chosen = [field for field in ("css", "label") if field in values]
    if len(chosen) > 1 or (chosen and attributes):
        raise ValueError(
            "css, label and placeholder/test_id each choose the candidates; give only one of them"
        )
    if "css" in values:
        return values["css"]
    if "label" in values:
        return _LABELLED
    return "".join(attributes) or None


def _attribute(attribute: str, value: str, *, exact: bool) -> str:
    literal = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"[{attribute}={literal}]" if exact else f"[{attribute}*={literal} i]"


def _collapse(value: str) -> str:
    """Whitespace-collapsed, the way the page collapses the names it renders."""
    return " ".join(value.split())
