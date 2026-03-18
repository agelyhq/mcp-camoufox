from __future__ import annotations

import os
from dataclasses import dataclass

from camoufox_mcp.browser.addons import DEFAULT_ADDON_URLS

VALID_OS = frozenset({"windows", "linux", "macos"})


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"


@dataclass(frozen=True)
class ServerConfig:
    headless: bool = True
    proxy: str | None = None
    camoufox_binary: str | None = None
    addon_urls: tuple[str, ...] = DEFAULT_ADDON_URLS
    s3: S3Config | None = None

    @classmethod
    def from_env(cls) -> ServerConfig:
        raw_addons = os.getenv("CAMOUFOX_ADDON_URLS")
        if raw_addons is None:
            addon_urls = DEFAULT_ADDON_URLS
        elif raw_addons.strip() == "":
            addon_urls = ()
        else:
            addon_urls = tuple(u.strip() for u in raw_addons.split(",") if u.strip())

        s3: S3Config | None = None
        endpoint = os.getenv("CAMOUFOX_S3_ENDPOINT") or None
        access_key = os.getenv("CAMOUFOX_S3_ACCESS_KEY") or None
        secret_key = os.getenv("CAMOUFOX_S3_SECRET_KEY") or None
        bucket = os.getenv("CAMOUFOX_S3_BUCKET") or None
        if endpoint and access_key and secret_key and bucket:
            s3 = S3Config(
                endpoint_url=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                bucket=bucket,
                region=os.getenv("CAMOUFOX_S3_REGION", "us-east-1"),
            )

        return cls(
            headless=os.getenv("CAMOUFOX_HEADLESS", "true").lower() == "true",
            proxy=os.getenv("CAMOUFOX_PROXY") or None,
            camoufox_binary=os.getenv("CAMOUFOX_BINARY") or None,
            addon_urls=addon_urls,
            s3=s3,
        )


@dataclass(frozen=True)
class SessionParams:
    profile: str
    target_os: str = "windows"
    viewport_width: int = 1280
    viewport_height: int = 800
    block_images: bool = False
    block_webrtc: bool = False
