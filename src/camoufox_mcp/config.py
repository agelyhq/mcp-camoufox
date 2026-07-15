from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from platformdirs import user_data_dir

from camoufox_mcp.session_defaults import SessionDefaults

VALID_OS = frozenset({"windows", "linux", "macos"})

DEFAULT_ADDON_URLS: tuple[str, ...] = (
    "https://addons.mozilla.org/firefox/downloads/latest/istilldontcareaboutcookies/latest.xpi",
)

_APP_NAME = "camoufox-mcp"


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration. The ONLY object built from ``os.environ``."""

    headless: bool | str
    proxy: dict[str, str] | None
    geoip_forced: bool
    data_dir: Path
    camoufox_binary: str | None
    addon_urls: tuple[str, ...]
    auto_update: bool
    session_defaults: SessionDefaults

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @classmethod
    def from_env(cls) -> ServerConfig:
        proxy = _parse_proxy(os.getenv("CAMOUFOX_PROXY"))
        data_dir = Path(os.getenv("CAMOUFOX_DATA_DIR") or user_data_dir(_APP_NAME))
        return cls(
            headless=_parse_headless(os.getenv("CAMOUFOX_HEADLESS")),
            proxy=proxy,
            geoip_forced=proxy is not None,
            data_dir=data_dir,
            camoufox_binary=os.getenv("CAMOUFOX_BINARY") or None,
            addon_urls=_parse_addons(os.getenv("CAMOUFOX_ADDON_URLS")),
            auto_update=(os.getenv("CAMOUFOX_AUTO_UPDATE", "true").lower() != "false"),
            session_defaults=_parse_session_defaults(),
        )


def _parse_headless(raw: str | None) -> bool | str:
    if raw is None:
        return False  # default: visible window
    value = raw.strip().lower()
    if value == "virtual":
        return "virtual"
    return value == "true"


def _parse_proxy(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.hostname:
        raise ValueError(f"Invalid CAMOUFOX_PROXY: {raw!r}")
    scheme = parsed.scheme or "http"
    host = parsed.hostname
    server = f"{scheme}://{host}:{parsed.port}" if parsed.port else f"{scheme}://{host}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def _parse_addons(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_ADDON_URLS
    if raw.strip() == "":
        return ()
    return tuple(u.strip() for u in raw.split(",") if u.strip())


def _parse_session_defaults() -> SessionDefaults:
    width, height = _parse_viewport(os.getenv("CAMOUFOX_VIEWPORT"))
    fingerprint_os = os.getenv("CAMOUFOX_FINGERPRINT_OS")
    if fingerprint_os is not None:
        fingerprint_os = fingerprint_os.strip().lower()
        if fingerprint_os not in VALID_OS:
            raise ValueError(
                f"Invalid CAMOUFOX_FINGERPRINT_OS={fingerprint_os!r}; "
                f"must be one of {', '.join(sorted(VALID_OS))}"
            )
    return SessionDefaults(
        fingerprint_os=fingerprint_os,
        viewport_width=width,
        viewport_height=height,
        locale=os.getenv("CAMOUFOX_LOCALE") or None,
    )


def _parse_viewport(raw: str | None) -> tuple[int | None, int | None]:
    if not raw:
        return None, None
    parts = raw.lower().split("x")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Invalid CAMOUFOX_VIEWPORT={raw!r}; expected e.g. '1280x720'")
    return int(parts[0]), int(parts[1])
