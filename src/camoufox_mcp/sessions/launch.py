from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions

_IS_LINUX = sys.platform.startswith("linux")

# Camoufox decides whether `humanize` carries a max cursor-travel time with
# `isinstance(humanize, (int, float))` — and in Python `isinstance(True, int)` is
# True, so passing the plain bool forwards `humanize:maxTime = true` to the browser.
# Firefox rejects it ("Value for key 'humanize:maxTime' is not a double") and the
# humanised cursor never completes a move: `Page.dispatchMouseEvent(mousemove)` then
# goes unanswered forever, hanging every click/hover that has to travel. Passing an
# explicit float keeps humanisation enabled and correctly typed. 1.5s is the
# window-traversal time Camoufox documents as typical.
_HUMANIZE_MAX_SECONDS = 1.5


def build_launch_kwargs(
    config: ServerConfig,
    opts: SessionInitOptions,
    user_data_dir: Path,
    addon_dirs: list[str],
) -> dict[str, Any]:
    """Translate config + resolved session options into Camoufox launch kwargs.

    Always-on: ``humanize=True``, ``persistent_context=True``. ``geoip`` is forced
    ``True`` whenever a proxy is configured (Camoufox leaks a warning otherwise).
    ``headless`` uses the per-session override when supplied, else the server-wide
    ``config.headless`` default.
    """
    headless = config.headless if opts.headless is None else opts.headless
    if headless == "virtual" and not _IS_LINUX:
        raise ValueError(
            "headless 'virtual' requires Linux (it spawns an Xvfb X server); "
            "use 'true' on this platform"
        )
    kwargs: dict[str, Any] = {
        "headless": headless,
        "humanize": _HUMANIZE_MAX_SECONDS,
        "persistent_context": True,
        "user_data_dir": str(user_data_dir),
        "block_images": opts.block_images,
        "block_webrtc": opts.block_webrtc,
    }
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
