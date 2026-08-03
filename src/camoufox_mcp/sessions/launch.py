from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions

_IS_LINUX = sys.platform.startswith("linux")

# Humanised cursor movement is opt-in (``CAMOUFOX_HUMANIZE``, off by default): with it
# on, Firefox intermittently stops answering the Juggler protocol part-way through a
# ``Page.dispatchMouseEvent`` while the process stays alive, so the pending click or
# hover never returns. Measured on the E2E suite: every run with it enabled froze at a
# random test, every run without it completed 145/145.
# When enabled, the value MUST reach Camoufox as a float. Camoufox decides whether
# ``humanize`` carries a max cursor-travel time with ``isinstance(humanize, (int,
# float))``, and Python's bool subclasses int — so a plain ``True`` forwards
# ``humanize:maxTime = true``, which Firefox rejects outright ("Value for key
# 'humanize:maxTime' is not a double").


def build_launch_kwargs(
    config: ServerConfig,
    opts: SessionInitOptions,
    user_data_dir: Path,
    addon_dirs: list[str],
) -> dict[str, Any]:
    """Translate config + resolved session options into Camoufox launch kwargs.

    Always-on: ``persistent_context=True``. ``geoip`` is forced ``True`` whenever a
    proxy is configured (Camoufox leaks a warning otherwise). ``headless`` uses the
    per-session override when supplied, else the server-wide ``config.headless``
    default. ``humanize`` is only sent when ``config.humanize`` is set.
    """
    headless = config.headless if opts.headless is None else opts.headless
    if headless == "virtual" and not _IS_LINUX:
        raise ValueError(
            "headless 'virtual' requires Linux (it spawns an Xvfb X server); "
            "use 'true' on this platform"
        )
    kwargs: dict[str, Any] = {
        "headless": headless,
        "persistent_context": True,
        "user_data_dir": str(user_data_dir),
        "block_images": opts.block_images,
        "block_webrtc": opts.block_webrtc,
    }
    if config.humanize is not None:
        kwargs["humanize"] = config.humanize
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
