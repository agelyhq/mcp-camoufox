from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from platformdirs import user_data_dir

from camoufox_mcp.session_defaults import SessionDefaults

VALID_OS = frozenset({"windows", "linux", "macos"})
VALID_HEADLESS = ("true", "false", "virtual")

DEFAULT_ADDON_URLS: tuple[str, ...] = (
    "https://addons.mozilla.org/firefox/downloads/latest/istilldontcareaboutcookies/latest.xpi",
)

_APP_NAME = "camoufox-mcp"


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (with parents) and force it to owner-only ``0o700``.

    ``mkdir``'s ``mode`` is masked by the process umask and ignored entirely for a
    pre-existing directory, so ``chmod`` re-runs afterwards to guarantee the mode.
    Apply ONLY to directories we own outright — they hold cookies, storage state
    and credential-bearing telemetry; never to a path the user might share.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def parse_headless(raw: str | None, *, unset: bool | str | None = False) -> bool | str | None:
    """Canonical ``CAMOUFOX_HEADLESS`` / ``headless`` parser and validator.

    ``unset`` is returned when ``raw`` is ``None``: the config layer passes
    ``False`` (a visible window is the server-wide default) while ``navigate``
    passes ``None`` so an omitted per-call override falls back to that default.
    ``"true"``/``"false"`` map to ``bool`` and ``"virtual"`` stays a string; any
    other value raises ``ValueError`` listing the valid names.
    """
    if raw is None:
        return unset
    value = raw.strip().lower()
    if value not in VALID_HEADLESS:
        raise ValueError(f"invalid headless '{raw}'; must be one of {', '.join(VALID_HEADLESS)}")
    if value == "virtual":
        return "virtual"
    return value == "true"


def validate_fingerprint_os(value: str) -> str:
    """Normalize and validate a fingerprint OS name against :data:`VALID_OS`.

    Returns the lowercased name; raises ``ValueError`` (listing the valid names)
    for anything outside ``{windows, linux, macos}``. Shared by the
    ``CAMOUFOX_FINGERPRINT_OS`` env parser and the ``navigate`` ``fingerprint_os``
    parameter so both reject invalid input with an identical message.
    """
    normalized = value.strip().lower()
    if normalized not in VALID_OS:
        raise ValueError(
            f"invalid fingerprint_os '{value}'; must be one of {', '.join(sorted(VALID_OS))}"
        )
    return normalized


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration. The ONLY object built from ``os.environ``."""

    headless: bool | str
    proxy: dict[str, str] | None
    data_dir: Path
    camoufox_binary: str | None
    addon_urls: tuple[str, ...]
    auto_update: bool
    session_defaults: SessionDefaults
    daemon_enabled: bool
    daemon_ttl_seconds: int

    @property
    def geoip_forced(self) -> bool:
        """Camoufox geoip is forced on whenever a proxy is configured."""
        return self.proxy is not None

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def daemon_dir(self) -> Path:
        """Private (0o700) home of the daemon socket, lock and log."""
        return self.data_dir / "daemon"

    @property
    def daemon_socket_path(self) -> Path:
        return self.daemon_dir / "daemon.sock"

    @property
    def daemon_endpoint_path(self) -> Path:
        """Windows advert file: the daemon's loopback host, port and bearer token."""
        return self.daemon_dir / "daemon.endpoint"

    @property
    def daemon_lock_path(self) -> Path:
        return self.daemon_dir / "daemon.lock"

    @property
    def daemon_log_path(self) -> Path:
        return self.daemon_dir / "daemon.log"

    def ensure_private_dirs(self) -> None:
        """Create the data root and its credential-bearing subdirs at ``0o700``.

        The composition-root call: cookies, storage state and telemetry all live
        under these directories, so none may be group/other-readable.
        """
        ensure_private_dir(self.data_dir)
        ensure_private_dir(self.profiles_dir)
        ensure_private_dir(self.logs_dir)

    def ensure_profiles_dir(self) -> Path:
        """Harden the data root, then create ``<data_dir>/profiles/`` (0o700)."""
        ensure_private_dir(self.data_dir)
        return ensure_private_dir(self.profiles_dir)

    def ensure_profile_dir(self, profile: str) -> Path:
        """Create this profile's own private directory under ``profiles/`` (0o700)."""
        self.ensure_profiles_dir()
        return ensure_private_dir(self.profiles_dir / profile)

    def ensure_daemon_dir(self) -> Path:
        """Create ``<data_dir>/daemon/`` restricted to the owner, then return it.

        The control channel's advert lives here: on POSIX a 0o700 parent keeps the
        Unix socket unreachable during the window before the endpoint tightens it to
        0o600, and on Windows it holds the bearer-token ``daemon.endpoint`` file.
        ``chmod`` re-runs after ``mkdir`` to defeat a permissive umask on a
        pre-existing directory (a near-no-op on Windows, where the token is the real
        boundary). Called by both the daemon (before binding) and the spawner.
        """
        ensure_private_dir(self.data_dir)
        return ensure_private_dir(self.daemon_dir)

    @classmethod
    def from_env(cls) -> ServerConfig:
        proxy = _parse_proxy(os.getenv("CAMOUFOX_PROXY"))
        data_dir = Path(os.getenv("CAMOUFOX_DATA_DIR") or user_data_dir(_APP_NAME))
        return cls(
            headless=parse_headless(os.getenv("CAMOUFOX_HEADLESS")),
            proxy=proxy,
            data_dir=data_dir,
            camoufox_binary=os.getenv("CAMOUFOX_BINARY") or None,
            addon_urls=_parse_addons(os.getenv("CAMOUFOX_ADDON_URLS")),
            auto_update=(os.getenv("CAMOUFOX_AUTO_UPDATE", "true").lower() != "false"),
            session_defaults=_parse_session_defaults(),
            daemon_enabled=(os.getenv("CAMOUFOX_DAEMON", "false").lower() == "true"),
            daemon_ttl_seconds=_parse_ttl(os.getenv("CAMOUFOX_DAEMON_TTL")),
        )


def _parse_ttl(raw: str | None) -> int:
    if raw is None or raw.strip() == "":
        return 1800
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid CAMOUFOX_DAEMON_TTL={raw!r}; expected a positive integer"
        ) from exc
    if value <= 0:
        raise ValueError(f"Invalid CAMOUFOX_DAEMON_TTL={raw!r}; must be > 0")
    return value


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
        fingerprint_os = validate_fingerprint_os(fingerprint_os)
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
