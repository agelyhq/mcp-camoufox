from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from platformdirs import user_data_dir

from camoufox_mcp.session_defaults import SessionDefaults

VALID_OS = frozenset({"windows", "linux", "macos"})
VALID_HEADLESS = ("true", "false", "virtual")

# Browser build this server is validated against, as `<firefox-version>-<build>`
# (the identifier `camoufox list` prints). The Camoufox Python pin does NOT hold the
# browser: unpinned, its launcher takes whatever GitHub release matches the library's
# release-ordinal range, so the binary drifts on its own. Pinning makes it a
# reviewable dependency, and the Playwright bound in pyproject.toml is chosen for
# THIS build's Juggler schema. See docs/decisions.md.
DEFAULT_BROWSER_VERSION = "152.0.4-beta.28"

# Value of ``CAMOUFOX_BROWSER_VERSION`` that opts out of the pin.
_BROWSER_VERSION_LATEST = "latest"

DEFAULT_ADDON_URLS: tuple[str, ...] = (
    "https://addons.mozilla.org/firefox/downloads/latest/istilldontcareaboutcookies/latest.xpi",
)

# Not the distribution name (`mcp-camoufox`), and deliberately so: this is the
# platformdirs key behind the default data dir, so renaming it would strand every
# existing profile and its logins. See docs/configuration.md.
_APP_NAME = "camoufox-mcp"


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (with parents) and force it to owner-only ``0o700``.

    ``mkdir``'s ``mode`` is masked by the process umask and ignored entirely for a
    pre-existing directory, so ``chmod`` re-runs afterwards to guarantee the mode.
    Apply ONLY to directories we own outright: they hold cookies, storage state
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
    runtime_dir: Path | None
    camoufox_binary: str | None
    browser_version: str | None
    addon_urls: tuple[str, ...]
    bundled_addons: bool
    auto_update: bool
    humanize: float | None
    session_defaults: SessionDefaults
    daemon_enabled: bool
    daemon_ttl_seconds: int

    @property
    def geoip_forced(self) -> bool:
        """Camoufox geoip is forced on whenever a proxy is configured."""
        return self.proxy is not None

    def launch_env(self) -> dict[str, str]:
        """A private copy of the process environment for exactly ONE browser launch.

        Camoufox defaults its ``env`` launch option to a *reference* to ``os.environ``
        and writes into it: ``headless='virtual'`` stores the throwaway Xvfb
        ``DISPLAY`` there (plus ``GDK_BACKEND``/``MOZ_ENABLE_WAYLAND``), repointing the
        whole server process at a 1x1 display. A fresh copy per launch keeps those
        writes inside that launch, so display modes can coexist in one process.
        """
        return dict(os.environ)

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def addons_dir(self) -> Path:
        """Cache of the extracted addon XPIs, governed by ``CAMOUFOX_DATA_DIR``."""
        return self.data_dir / "addons"

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

    def ensure_addons_dir(self) -> Path:
        """Harden the data root, then create ``<data_dir>/addons/`` (0o700)."""
        ensure_private_dir(self.data_dir)
        return ensure_private_dir(self.addons_dir)

    @classmethod
    def from_env(cls) -> ServerConfig:
        proxy = _parse_proxy(os.getenv("CAMOUFOX_PROXY"))
        data_dir = Path(os.getenv("CAMOUFOX_DATA_DIR") or user_data_dir(_APP_NAME))
        return cls(
            headless=parse_headless(os.getenv("CAMOUFOX_HEADLESS")),
            proxy=proxy,
            data_dir=data_dir,
            runtime_dir=_parse_runtime_dir(os.getenv("XDG_RUNTIME_DIR")),
            camoufox_binary=os.getenv("CAMOUFOX_BINARY") or None,
            browser_version=_parse_browser_version(os.getenv("CAMOUFOX_BROWSER_VERSION")),
            addon_urls=_parse_addons(os.getenv("CAMOUFOX_ADDON_URLS")),
            bundled_addons=(os.getenv("CAMOUFOX_BUNDLED_ADDONS", "true").lower() != "false"),
            auto_update=(os.getenv("CAMOUFOX_AUTO_UPDATE", "true").lower() != "false"),
            humanize=_parse_humanize(os.getenv("CAMOUFOX_HUMANIZE")),
            session_defaults=_parse_session_defaults(),
            daemon_enabled=(os.getenv("CAMOUFOX_DAEMON", "false").lower() == "true"),
            daemon_ttl_seconds=_parse_ttl(os.getenv("CAMOUFOX_DAEMON_TTL")),
        )


def _parse_runtime_dir(raw: str | None) -> Path | None:
    """Parse ``XDG_RUNTIME_DIR`` into the per-user runtime root, or ``None``.

    Short, per user and already owner-only, it is where the daemon's POSIX control
    socket must live: an AF_UNIX ``sun_path`` cannot hold an arbitrary data dir. A
    value naming something that is not a directory is treated as unset, so a stale
    variable falls back to the data dir rather than failing a bind.
    """
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


def _parse_browser_version(raw: str | None) -> str | None:
    """Parse ``CAMOUFOX_BROWSER_VERSION`` into a Camoufox browser build selector.

    Unset means :data:`DEFAULT_BROWSER_VERSION`: the pin is the default, because a
    server that silently follows the newest Firefox is a server whose Playwright
    bound is a guess. Set another ``<version>-<build>`` (see ``camoufox list``) to run
    a different build, or ``latest``/empty to let Camoufox chase the newest release.
    Ignored when ``CAMOUFOX_BINARY`` names an executable outright.
    """
    if raw is None:
        return DEFAULT_BROWSER_VERSION
    value = raw.strip()
    if value == "" or value.lower() == _BROWSER_VERSION_LATEST:
        return None
    return value


def _parse_humanize(raw: str | None) -> float | None:
    """Parse ``CAMOUFOX_HUMANIZE`` into a max cursor-travel time, or ``None`` when off.

    Humanised cursor movement is OPT-IN because it intermittently wedges the browser:
    Camoufox interpolates the motion inside Firefox, and the process then stops
    answering the Juggler protocol mid-``Page.dispatchMouseEvent`` while staying
    alive, so the pending call never returns. Measured on the E2E suite: every run
    with humanisation on froze at a random test, while runs with it off completed
    145/145. Set the variable to a duration in seconds (e.g. ``1.5``) to accept that
    risk in exchange for the anti-detection benefit.
    """
    if raw is None or raw.strip() == "" or raw.strip().lower() in {"false", "off", "0"}:
        return None
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid CAMOUFOX_HUMANIZE={raw!r}; expected a duration in seconds "
            "(e.g. '1.5'), or 'false' to disable"
        ) from exc
    if value <= 0:
        raise ValueError(f"Invalid CAMOUFOX_HUMANIZE={raw!r}; must be > 0")
    return value


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
