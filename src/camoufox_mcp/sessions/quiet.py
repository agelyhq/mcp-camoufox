from __future__ import annotations

import io
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import TextIO


class _StdioSilencer:
    """Reference-counted swap of the process streams for a throwaway sink.

    Camoufox prints its first-launch progress (browser download, GeoIP database)
    with plain ``print``, from the worker thread ``AsyncNewBrowser`` runs
    ``launch_options`` in, and exposes no hook to redirect it, so the only lever is
    the process-global streams. That makes the swap concurrency-sensitive: session
    creation is locked per profile, so two launches can overlap, and plain nesting
    corrupts the restore (the inner block hands the outer block's sink back as "the"
    stdout and the real stream never returns). Counting entries and restoring only
    what the FIRST one saved keeps that impossible. Nothing here awaits, so the
    counter cannot be observed half-updated by another task.
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
