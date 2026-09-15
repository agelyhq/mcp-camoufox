"""This process never assigns ``sys.stdout`` or ``sys.stderr``: the source is parsed to prove it.

A swap of the process streams is process-global whichever thread performs it, and the
stdio transport reads ``sys.stdout`` when it starts: fastmcp 4 suspends between our
lifespan's ``yield`` and that read, and a background refresh that redirected the streams
from a worker thread in that window handed mcp a ``StringIO``, an ``AttributeError`` on
``.buffer``, and a host reporting "Connection closed" on every start. The fetches now
run in a child process (``updater/child.py``); this test keeps the swap from coming back
anywhere under ``src/``, in any spelling the language offers: a bare, annotated,
augmented or tuple assignment, a ``with ... as`` or ``del`` target, ``setattr``, a write
into ``vars(sys)`` or ``sys.__dict__``, ``sys`` imported under another name, and
``contextlib.redirect_stdout``/``redirect_stderr`` however they are imported or aliased.
The guard walks the AST rather than matching text, so a docstring naming the swap is not
a swap, and a swap split across a line or hidden behind an alias still is one.

The single exemption is ``sessions/quiet.py``, kept because camoufox's launch thread
prints with bare ``print`` and rich against the live streams and offers no other sink,
and safe because a session can only be created by a tool call, which can only arrive
over a transport that already holds its own handle on fd 1. The file states that
invariant; this test states the exemption, so the 2 cannot drift apart silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "camoufox_mcp"

STREAMS = frozenset({"stdout", "stderr", "__stdout__", "__stderr__"})
REDIRECTS = frozenset({"redirect_stdout", "redirect_stderr"})
SYS_MODULE = "sys"
CONTEXTLIB_MODULE = "contextlib"

# The one file allowed to swap the streams, and why, in the sentence its docstring must
# keep: the exemption is earned by the invariant, not by the filename.
EXEMPT = Path("sessions") / "quiet.py"
EXEMPTION_REASON = "the stdio transport claims fd 1 before"


def swaps_in(source: str) -> list[str]:
    """Every process-global stream swap in ``source``, as ``"<line>: <text>"``.

    ``sys`` is whatever ``import sys [as name]`` binds in the file, so an alias hides
    nothing. A ``setattr``, ``vars(sys)[...]`` or ``sys.__dict__[...]`` whose attribute
    name is not a literal is reported too: a name computed at runtime cannot be proved
    harmless by reading the file.
    """
    tree = ast.parse(source)
    sys_names = _module_aliases(tree, SYS_MODULE)
    lines = source.splitlines()
    swap_lines = {node.lineno for node in ast.walk(tree) if _is_swap(node, sys_names)}
    return [f"{lineno}: {lines[lineno - 1].strip()}" for lineno in sorted(swap_lines)]


def _module_aliases(tree: ast.Module, module: str) -> frozenset[str]:
    names = {module}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.asname or a.name for a in node.names if a.name == module)
    return frozenset(names)


def _is_swap(node: ast.AST, sys_names: frozenset[str]) -> bool:
    if isinstance(node, ast.Attribute):
        return _is_stream_write(node, sys_names) or node.attr in REDIRECTS
    if isinstance(node, ast.Name):
        return node.id in REDIRECTS
    if isinstance(node, ast.ImportFrom):
        return node.module == CONTEXTLIB_MODULE and any(a.name in REDIRECTS for a in node.names)
    if isinstance(node, ast.Call):
        return _is_setattr_on_sys(node, sys_names)
    if isinstance(node, ast.Subscript):
        return _is_sys_dict_write(node, sys_names)
    return False


def _is_stream_write(node: ast.Attribute, sys_names: frozenset[str]) -> bool:
    """``sys.stdout`` as an assignment, ``with``/``for`` or ``del`` target, never as a read."""
    return (
        not isinstance(node.ctx, ast.Load)
        and _is_sys(node.value, sys_names)
        and node.attr in STREAMS
    )


def _is_setattr_on_sys(node: ast.Call, sys_names: frozenset[str]) -> bool:
    if not (isinstance(node.func, ast.Name) and node.func.id == "setattr"):
        return False
    if len(node.args) < 2 or not _is_sys(node.args[0], sys_names):
        return False
    return _names_a_stream(node.args[1])


def _is_sys_dict_write(node: ast.Subscript, sys_names: frozenset[str]) -> bool:
    """``vars(sys)[...] = ...`` or ``sys.__dict__[...] = ...`` (or ``del`` of either)."""
    if isinstance(node.ctx, ast.Load):
        return False
    container = node.value
    if isinstance(container, ast.Call):
        is_sys_dict = (
            isinstance(container.func, ast.Name)
            and container.func.id == "vars"
            and len(container.args) == 1
            and _is_sys(container.args[0], sys_names)
        )
    else:
        is_sys_dict = (
            isinstance(container, ast.Attribute)
            and container.attr == "__dict__"
            and _is_sys(container.value, sys_names)
        )
    return is_sys_dict and _names_a_stream(node.slice)


def _is_sys(node: ast.AST, sys_names: frozenset[str]) -> bool:
    return isinstance(node, ast.Name) and node.id in sys_names


def _names_a_stream(node: ast.AST) -> bool:
    """A literal naming a stream, or anything that is not a literal at all."""
    if isinstance(node, ast.Constant):
        return node.value in STREAMS
    return True


def _source_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, f"no sources under {SRC}"
    return files


def test_no_source_file_swaps_the_process_streams() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _source_files():
        if path.relative_to(SRC) == EXEMPT:
            continue
        hits = swaps_in(path.read_text(encoding="utf-8"))
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
    assert swaps_in(text), f"{EXEMPT} no longer swaps the streams: drop the exemption"
    assert EXEMPTION_REASON in text, f"{EXEMPT} must state the invariant that makes it safe"


# Each spelling of a swap, with the one hit the guard must report for it: a preamble
# line (an import, an alias) is context, never a hit of its own.
SPELLINGS = [
    (
        "with contextlib.redirect_stdout(io.StringIO()):\n    pass",
        "1: with contextlib.redirect_stdout(io.StringIO()):",
    ),
    ("with redirect_stderr(sink):\n    pass", "1: with redirect_stderr(sink):"),
    (
        "from contextlib import redirect_stdout as hush",
        "1: from contextlib import redirect_stdout as hush",
    ),
    ("import contextlib as c\nc.redirect_stderr(sink)", "2: c.redirect_stderr(sink)"),
    ("sys.stdout = sys.stderr = io.StringIO()", "1: sys.stdout = sys.stderr = io.StringIO()"),
    ("if quiet:\n    sys.stderr = open(os.devnull, 'w')", "2: sys.stderr = open(os.devnull, 'w')"),
    ("sys.__stdout__ = sink", "1: sys.__stdout__ = sink"),
    ("sys.__stderr__ = sink", "1: sys.__stderr__ = sink"),
    ("sys.stdout: TextIO = sink", "1: sys.stdout: TextIO = sink"),
    ("sys.stdout += sink", "1: sys.stdout += sink"),
    ("(sys.stdout, sys.stderr) = sinks", "1: (sys.stdout, sys.stderr) = sinks"),
    ("sys.stdout, other = sinks", "1: sys.stdout, other = sinks"),
    ("[other, sys.stderr] = sinks", "1: [other, sys.stderr] = sinks"),
    ("with open(path) as sys.stdout:\n    pass", "1: with open(path) as sys.stdout:"),
    ("for sys.stdout in sinks:\n    pass", "1: for sys.stdout in sinks:"),
    ("del sys.stdout", "1: del sys.stdout"),
    ('setattr(sys, "stdout", sink)', '1: setattr(sys, "stdout", sink)'),
    ("setattr(sys, name, sink)", "1: setattr(sys, name, sink)"),
    ('vars(sys)["stderr"] = sink', '1: vars(sys)["stderr"] = sink'),
    ("vars(sys)[name] = sink", "1: vars(sys)[name] = sink"),
    ('sys.__dict__["stdout"] = sink', '1: sys.__dict__["stdout"] = sink'),
    ("import sys as system\nsystem.stdout = sink", "2: system.stdout = sink"),
]


@pytest.mark.parametrize(("source", "expected"), SPELLINGS, ids=[hit for _, hit in SPELLINGS])
def test_the_guard_detects_each_spelling(source: str, expected: str) -> None:
    """Control: each spelling is caught, on its own line, before its absence is asserted."""
    assert swaps_in(source) == [expected]


@pytest.mark.parametrize(
    "source",
    [
        'print("x", file=sys.stderr)',
        "sys.stderr.write(text)",
        "saved = (sys.stdout, sys.stderr)",
        "sys.stderr.buffer.write(data)",
        "streams[sys.stdout] = name",
        'setattr(obj, "stdout", sink)',
        'setattr(sys, "ps1", prompt)',
        'vars(obj)["stdout"] = sink',
        '"""sys.stdout = never, says this docstring"""',
        "# sys.stderr = a comment is not a swap",
    ],
    ids=lambda source: source,
)
def test_the_guard_ignores_a_read(source: str) -> None:
    """Control: reading or naming a stream is not swapping it, or the guard is noise."""
    assert swaps_in(source) == []
