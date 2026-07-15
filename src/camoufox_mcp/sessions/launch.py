from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions


def build_launch_kwargs(
    config: ServerConfig,
    opts: SessionInitOptions,
    user_data_dir: Path,
    addon_dirs: list[str],
) -> dict[str, Any]:
    """Translate config + resolved session options into Camoufox launch kwargs.

    Always-on: ``humanize=True``, ``persistent_context=True``. ``geoip`` is forced
    ``True`` whenever a proxy is configured (Camoufox leaks a warning otherwise).
    """
    kwargs: dict[str, Any] = {
        "headless": config.headless,
        "humanize": True,
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
