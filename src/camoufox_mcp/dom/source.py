from __future__ import annotations

import functools
from pathlib import Path

_JS_DIR = Path(__file__).resolve().parent / "js"

# Concatenation order. Only the last file ends with a top-level ``return``.
_ORDER = (
    "00_boot.js",
    "10_visibility.js",
    "20_names.js",
    "30_walk.js",
    "40_selector.js",
    "45_query.js",
    "50_geometry.js",
    "60_actions.js",
    "65_extract.js",
    "70_ops.js",
)

# One constant dispatch expression, so the bundle crosses the protocol once per
# document and every operation afterwards costs a tiny payload. ``a.op`` is always
# a literal from OPS, never caller input.
DISPATCH = "(store, a) => store.ops[a.op](a)"

OPS = frozenset(
    {
        "capture",
        "extract",
        "locate",
        "resolve",
        "scrollTo",
        "prepareFill",
        "selectOptions",
        "selectOption",
        "setFiles",
        "evaluate",
    }
)


@functools.cache
def bundle() -> str:
    """The whole element store as one parenthesised arrow expression, read once.

    Evaluating it yields a plain JS object. Its remote subtype is ``object`` and
    never ``node``, which is the whole point: no node handle is ever created, so no
    driver-side injected script is instantiated in the page's own world.
    """
    parts = [(_JS_DIR / name).read_text(encoding="utf-8") for name in _ORDER]
    return "(() => {\n" + "\n".join(parts) + "\n})"


def seeded_store(seed: int) -> str:
    """The store bundle wrapped so its uid counter starts at ``seed``.

    The write is a plain assignment to a property the bundle already owns, so it
    reaches no page-reachable global and a page that has replaced ``Object`` or any
    prototype accessor observes nothing.

    Composing the page-side source belongs here with the source it composes: the
    registry owns the handle lifecycle and never spells JS.
    """
    return f"(() => {{\nconst store = ({bundle()})();\nstore.n = {seed};\nreturn store;\n}})"
