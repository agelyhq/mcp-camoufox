from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions

IS_LINUX = sys.platform.startswith("linux")

# Humanised cursor movement is opt-in (``CAMOUFOX_HUMANIZE``, off by default): with it
# on, Firefox intermittently stops answering the Juggler protocol part-way through a
# ``Page.dispatchMouseEvent`` while the process stays alive, so the pending click or
# hover never returns. Re-measured 2026-08-03 against a 152.0.4-beta.28 binary that
# already carries the two upstream fixes: a missed hit-renderer acknowledgement still
# wedges a process-global dispatch chain permanently, with no upstream timeline. It has
# happened in production, not only under test: one click_at ran for 2,004,856 ms.
# When enabled, the value MUST reach Camoufox as a float. Camoufox decides whether
# ``humanize`` carries a max cursor-travel time with ``isinstance(humanize, (int,
# float))`` and never excludes bool, which subclasses int, so a plain ``True`` forwards
# ``humanize:maxTime = true``, which Firefox rejects outright ("Value for key
# 'humanize:maxTime' is not a double"). Still true of camoufox 0.5.4.


def build_launch_kwargs(
    config: ServerConfig,
    opts: SessionInitOptions,
    user_data_dir: Path,
    addon_dirs: list[str],
) -> dict[str, Any]:
    """Translate config + resolved session options into Camoufox launch kwargs.

    Always-on: ``persistent_context=True`` and a private ``env`` copy. ``geoip`` is
    forced ``True`` whenever a proxy is configured (Camoufox leaks a warning
    otherwise). ``headless`` uses the per-session override when supplied, else the
    server-wide ``config.headless`` default. ``humanize`` is only sent when
    ``config.humanize`` is set, and ``browser`` only when a build is pinned.

    Never returns ``viewport`` or ``no_viewport``: Camoufox's ``AsyncNewBrowser``
    defaults a window-spoofing persistent context to ``no_viewport=True`` and only
    when the caller supplied neither key. That default is what keeps Playwright from
    asking Juggler to resize a window Camoufox has pinned, a handshake with no
    timeout (daijro/camoufox#666).
    """
    headless = config.headless if opts.headless is None else opts.headless
    if headless == "virtual" and not IS_LINUX:
        raise ValueError(
            "headless 'virtual' requires Linux (it spawns an Xvfb X server); "
            "use 'true' on this platform"
        )
    if bool(opts.viewport_width) != bool(opts.viewport_height):
        # Camoufox pins a window, not an axis, so half a pair is not a smaller
        # request: it is a request this function cannot honour. Dropping it silently
        # launched a default-sized window and left the caller to discover it.
        raise ValueError(
            "viewport_width and viewport_height must be supplied together; a window size needs both"
        )
    kwargs: dict[str, Any] = {
        "headless": headless,
        "persistent_context": True,
        "user_data_dir": str(user_data_dir),
        "block_images": opts.block_images,
        "block_webrtc": opts.block_webrtc,
        "env": config.launch_env(),
    }
    if config.humanize is not None:
        kwargs["humanize"] = config.humanize
    if config.browser_version:
        kwargs["browser"] = config.browser_version
    if opts.fingerprint_os:
        kwargs["os"] = opts.fingerprint_os
    if opts.locale:
        kwargs["locale"] = opts.locale
    if opts.viewport_width and opts.viewport_height:
        kwargs["window"] = (opts.viewport_width, opts.viewport_height)
    if addon_dirs:
        kwargs["addons"] = addon_dirs
    if config.proxy:
        kwargs["proxy"] = config.proxy
    if config.geoip_forced:
        kwargs["geoip"] = True
    if config.camoufox_binary:
        kwargs["executable_path"] = config.camoufox_binary
    return kwargs
