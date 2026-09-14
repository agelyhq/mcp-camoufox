"""The fetch child: download 1 Camoufox asset, then exit. Never starts the server.

Run as ``python -m camoufox_mcp.updater.fetch <browser|geoip>`` by :mod:`.child`, with
stdin and stdout on the null device and stderr on a pipe the parent keeps a bounded tail
of. Camoufox reports download progress with plain ``print`` and rich, both resolved
against the process streams at call time and exposing no other sink, so the only place
that output can go without a process-global stream swap is a process of its own. The
child re-derives its :class:`ServerConfig` from the environment the parent copied to it.

Nothing here activates a build: activation is a local config write the parent owns
(:mod:`.builds`), so the child does exactly what needs the network and nothing else.
"""

from __future__ import annotations

import contextlib
import sys
from typing import TYPE_CHECKING, Literal, get_args

from camoufox_mcp.config import ServerConfig
from camoufox_mcp.updater.builds import installed_build
from camoufox_mcp.updater.errors import BrowserSetupError

if TYPE_CHECKING:
    from collections.abc import Sequence

FetchAsset = Literal["browser", "geoip"]
FETCH_ASSETS: tuple[str, ...] = get_args(FetchAsset)
USAGE_EXIT_STATUS = 2


def fetch_browser(version: str | None) -> None:
    """Install ``version`` if it is absent, or chase the newest release when ``None``.

    A pin is a promise not to move: once the build is on disk this never contacts
    GitHub. Unpinned, camoufox's own updater decides, and it activates what it installs.
    """
    purge_legacy_layout()
    if version is None:
        from camoufox.__main__ import CamoufoxUpdate

        # i_know_what_im_doing skips a click.confirm() prompt on a prerelease, which
        # would read stdin: the null device here, and a hang in any process holding
        # the MCP transport.
        CamoufoxUpdate().update(i_know_what_im_doing=True)
        return
    if installed_build(version) is None:
        install_build(version)


def install_build(version: str) -> None:
    from camoufox.pkgman import CamoufoxFetcher, list_available_versions

    for candidate in list_available_versions(include_prerelease=True):
        if candidate.version.full_string == version:
            CamoufoxFetcher(selected_version=candidate).install()
            return
    raise BrowserSetupError(
        f"Camoufox browser build {version!r} is not offered for this platform. "
        "Run `camoufox sync && camoufox list` to see the available builds, then set "
        "CAMOUFOX_BROWSER_VERSION to one of them."
    )


def fetch_geoip() -> None:
    from camoufox.geolocation import download_mmdb

    download_mmdb()


def purge_legacy_layout() -> None:
    """Let camoufox drop a pre-0.5 flat cache before anything installs into the new one.

    ``camoufox_path()`` is called for that side effect only: left in place, the stale
    copy is stranded forever once a versioned build lands next to it. It prints while
    purging ("Cleaning old data...") and raises when nothing is installed, which is why
    it runs here, in the child, and never in the server process.
    """
    with contextlib.suppress(Exception):
        from camoufox.pkgman import camoufox_path

        camoufox_path(download_if_missing=False)


def main(argv: Sequence[str]) -> int:
    """Fetch the asset named by ``argv[1]``; 0 on success, 1 with 1 line on stderr otherwise.

    The failure is rendered as ``<Type>: <message>`` and never as a traceback: the parent
    appends this stream's tail to the server log, and a stack of camoufox frames there
    says less than the exception that ended them.
    """
    if len(argv) != 2 or argv[1] not in FETCH_ASSETS:
        print(
            f"usage: python -m camoufox_mcp.updater.fetch <{'|'.join(FETCH_ASSETS)}>",
            file=sys.stderr,
        )
        return USAGE_EXIT_STATUS
    config = ServerConfig.from_env()
    try:
        if argv[1] == "browser":
            fetch_browser(config.browser_version)
        else:
            fetch_geoip()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
