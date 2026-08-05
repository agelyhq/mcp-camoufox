"""One read per element property, run against live elements through the element store.

Every script in ``js/reads`` is one synchronous expression returning one record per
element, with ``ok: false`` when the property does not apply to that element: an
empty string would be indistinguishable from an empty field. Rendering those records
is the caller's business; producing them is this module's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom.identity import scroll_uid
from camoufox_mcp.dom.scripting import evaluate_with_uids

if TYPE_CHECKING:
    from camoufox_mcp.dom.page_protocol import RegistryPage

_READS_DIR = Path(__file__).resolve().parent / "js" / "reads"

# Every property that has a read, in the order the tool surface advertises them.
READABLE_PROPS = ("text", "value", "attribute", "state", "box", "style")

# Properties whose script needs a name from the caller, substituted for this token.
NAMED_PROPS = ("attribute", "style")
_NAME_TOKEN = "__NAME__"

# A box is only worth reading if the caller can act on it, and click_at takes viewport
# pixels, so the element has to be inside the viewport when it is measured. That is the
# same scroll the uid action path performs before it acts: without it an element below
# the fold reports a point no click can reach, and both tools report success while
# nothing happens.
_SCROLLED_PROP = "box"

_CACHE: dict[str, str] = {}


async def read_property(
    page: RegistryPage, prop: str, uids: list[str], name: str | None = None
) -> list[Any]:
    """One record per uid for ``prop``, read in a single page turn where possible.

    ``name`` is the attribute or CSS property the named reads need. ``box`` is the
    exception to the single turn: each element is scrolled into view and measured on
    its own, because a measurement taken outside the viewport cannot be clicked.
    """
    script = _script_for(prop, name)
    records = await _run(page, prop, script, uids)
    if len(records) != len(uids):
        raise ValueError(f"the page returned no readable record for prop '{prop}'")
    return records


async def _run(page: RegistryPage, prop: str, script: str, uids: list[str]) -> list[Any]:
    if prop != _SCROLLED_PROP:
        result = await evaluate_with_uids(page, script, uids)
        return result if isinstance(result, list) else []
    records: list[Any] = []
    for uid in uids:
        await scroll_uid(page, uid)
        measured = await evaluate_with_uids(page, script, [uid])
        records.extend(measured if isinstance(measured, list) else [measured])
    return records


def _script_for(prop: str, name: str | None) -> str:
    """The read for ``prop``, with ``name`` embedded as a JSON string literal.

    JSON encoding is what keeps a caller-supplied name a value: interpolating it raw
    would let it close the string and continue as code in the page.
    """
    if prop not in READABLE_PROPS:
        raise ValueError(f"no page read exists for prop '{prop}'")
    script = _source(prop)
    if prop in NAMED_PROPS:
        return script.replace(_NAME_TOKEN, json.dumps(name))
    return script


def _source(prop: str) -> str:
    """The script's text, cached, with its full-line comments stripped.

    The rationale in those comments is written for whoever edits the file; the page
    is sent the expression only, on every call, so it does not pay for the prose.
    """
    if prop not in _CACHE:
        raw = (_READS_DIR / f"{prop}.js").read_text(encoding="utf-8")
        kept = [line for line in raw.splitlines() if not line.lstrip().startswith("//")]
        _CACHE[prop] = "\n".join(kept).strip()
    return _CACHE[prop]
