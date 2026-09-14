from __future__ import annotations

import io
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO


class _StdioSilencer:
    """Reference-counted swap of the process streams for a throwaway sink, around a launch.

    The 1 place this process assigns ``sys.stdout``/``sys.stderr``, and it is kept
    because nothing narrower reaches what it silences. ``AsyncNewBrowser`` runs
    camoufox's ``launch_options`` in a worker thread, and that thread writes with bare
    ``print`` and a rich ``Console`` that resolve the process streams at call time:
    ``camoufox_path()`` (reached unconditionally through ``get_path("fonts")``) purges a
    pre-0.5 cache with "Cleaning old data..." and downloads a build when the active one is
    unsupported, ``maybe_download_addons`` fetches the bundled addons with a progress bar
    on a first launch, and ``get_geolocation`` re-downloads the GeoIP database whenever
    upstream's own ``needs_update()`` says so. None of it is a launch option, a logging
    level or a driver pipe, and a stray line on fd 1 corrupts the MCP framing, so the
    swap is the protection here, not the hazard.

    What makes it safe is an ordering invariant: the stdio transport claims fd 1 before
    any session exists. ``SessionManager`` creates sessions lazily, on the first tool
    call for a profile, and a tool call can only arrive over a transport that is already
    running, so the transport already holds its own handle on stdout (a duplicated fd or
    the captured buffer, depending on the mcp version) when this swap happens and never
    reads ``sys.stdout`` again. The auto-update path has no such invariant, which is why
    its fetches run in a child process instead (``updater/child.py``), and why
    ``tests/test_no_stream_swaps.py`` exempts this file alone.

    The swap is also concurrency-sensitive: session creation is locked per profile, so
    two launches can overlap, and plain nesting corrupts the restore (the inner block
    hands the outer block's sink back as "the" stdout and the real stream never
    returns). Counting entries and restoring only what the FIRST one saved keeps that
    impossible. Nothing here awaits, so the counter cannot be observed half-updated by
    another task.
    """

    def __init__(self) -> None:
        self._depth = 0
        self._saved: tuple[TextIO, TextIO] | None = None

    @contextmanager
    def scope(self) -> Iterator[None]:
        self._enter()
        try:
            yield
        finally:
            self._exit()

    def _enter(self) -> None:
        if self._depth == 0:
            self._saved = (sys.stdout, sys.stderr)
            sys.stdout = sys.stderr = io.StringIO()
        self._depth += 1

    def _exit(self) -> None:
        self._depth -= 1
        if self._depth == 0 and self._saved is not None:
            sys.stdout, sys.stderr = self._saved
            self._saved = None


quiet_stdio = _StdioSilencer().scope
