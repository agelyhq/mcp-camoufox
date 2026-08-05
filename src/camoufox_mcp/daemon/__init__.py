"""The opt-in shared daemon and the stdio proxy in front of it.

Deliberately free of re-exports. Every caller names the module it needs
(``daemon.errors``, ``daemon.paths``, ``daemon.spawn``), so importing this package
to reach one of them never drags the rest of the control plane in with it: the
default non-daemon server must import on every platform without touching the
POSIX-only spawn machinery.
"""

from __future__ import annotations
