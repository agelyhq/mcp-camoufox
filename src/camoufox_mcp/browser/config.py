from __future__ import annotations

import os
from dataclasses import dataclass

from camoufox_mcp.browser.addons import DEFAULT_ADDON_URLS

VALID_OS = frozenset({"windows", "linux", "macos"})


@dataclass(frozen=True)
class ServerConfig:
    headless: bool = True
    proxy: str | None = None
    camoufox_binary: str | None = None
    profiles_dir: str | None = None
    addon_urls: tuple[str, ...] = DEFAULT_ADDON_URLS

    @classmethod
    def from_env(cls) -> ServerConfig:
        raw_addons = os.getenv("CAMOUFOX_ADDON_URLS")
        if raw_addons is None:
            addon_urls = DEFAULT_ADDON_URLS
        elif raw_addons.strip() == "":
            addon_urls = ()
        else:
            addon_urls = tuple(u.strip() for u in raw_addons.split(",") if u.strip())

        return cls(
            headless=os.getenv("CAMOUFOX_HEADLESS", "true").lower() == "true",
            proxy=os.getenv("CAMOUFOX_PROXY") or None,
            camoufox_binary=os.getenv("CAMOUFOX_BINARY") or None,
            profiles_dir=os.getenv("CAMOUFOX_PROFILES_DIR") or None,
            addon_urls=addon_urls,
        )


@dataclass(frozen=True)
class SessionParams:
    target_os: str = "windows"
    viewport_width: int = 1280
    viewport_height: int = 800
    profile: str | None = None
    block_images: bool = False
    block_webrtc: bool = False
