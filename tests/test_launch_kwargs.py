from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

from tests.helpers import isolate_camoufox_env

if TYPE_CHECKING:
    from pathlib import Path

# A display number that cannot exist on the runner, used to prove a launch never
# silently falls back to the ambient DISPLAY.
ABSENT_DISPLAY = ":424"


def _kwargs(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    viewport: tuple[int, int] | None = None,
    **env: str,
) -> dict[str, Any]:
    """Build the Camoufox launch kwargs an isolated server would use.

    ``viewport`` goes through the per-call override rather than ``CAMOUFOX_VIEWPORT``
    because ``isolate_camoufox_env`` clears that variable last, on purpose.
    """
    isolate_camoufox_env(monkeypatch, data_dir, **env)

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions
    from camoufox_mcp.sessions.launch import build_launch_kwargs

    config = ServerConfig.from_env()
    width, height = viewport or (None, None)
    opts = SessionInitOptions.resolve(
        config.session_defaults, viewport_width=width, viewport_height=height
    )
    return build_launch_kwargs(config, opts, data_dir / "profile", [])


def test_launch_env_is_a_private_copy(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every launch gets its own env dict, so nothing it writes escapes the process.

    Camoufox defaults ``env`` to a reference to ``os.environ`` and stores the Xvfb
    ``DISPLAY`` in it, which is how a virtual session used to repoint the whole
    process at a 1x1 display (issue #5). Two builds must not share a dict either, or
    two concurrent sessions would trample each other's display.
    """
    monkeypatch.setenv("DISPLAY", ABSENT_DISPLAY)

    first = _kwargs(data_dir, monkeypatch)["env"]
    second = _kwargs(data_dir, monkeypatch)["env"]

    assert first is not os.environ
    assert first is not second
    assert first["DISPLAY"] == ABSENT_DISPLAY

    first["DISPLAY"] = ":99"
    assert os.environ["DISPLAY"] == ABSENT_DISPLAY
    assert second["DISPLAY"] == ABSENT_DISPLAY


def test_launch_never_sets_a_viewport(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither ``viewport`` nor ``no_viewport`` may be passed.

    Camoufox defaults a window-spoofing persistent context to ``no_viewport=True``,
    but only when the caller supplied neither key. Supplying one silently opts us out
    of the guard against the unbounded Juggler resize handshake.
    """
    kwargs = _kwargs(data_dir, monkeypatch, viewport=(900, 700))

    assert "viewport" not in kwargs
    assert "no_viewport" not in kwargs
    assert kwargs["window"] == (900, 700)


def test_humanize_is_off_by_default(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMOUFOX_HUMANIZE", raising=False)
    assert "humanize" not in _kwargs(data_dir, monkeypatch)


def test_humanize_reaches_camoufox_as_a_float(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When enabled, humanize must be a float and never a bool.

    Camoufox forwards the value with ``isinstance(humanize, (int, float))`` and does
    not special-case ``bool``, which subclasses ``int``. A ``True`` would therefore
    reach Firefox as ``humanize:maxTime = true`` and be rejected outright ("Value for
    key 'humanize:maxTime' is not a double"), killing the launch.
    """
    kwargs = _kwargs(data_dir, monkeypatch, CAMOUFOX_HUMANIZE="1.5")

    assert kwargs["humanize"] == 1.5
    assert isinstance(kwargs["humanize"], float)
    assert not isinstance(kwargs["humanize"], bool)


def test_humanize_rejects_a_boolean_word(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="CAMOUFOX_HUMANIZE"):
        _kwargs(data_dir, monkeypatch, CAMOUFOX_HUMANIZE="true")


def test_browser_build_is_pinned_by_default(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unconfigured server launches the build the project is validated against.

    Without this the Camoufox launcher takes whatever GitHub release matches its
    release-ordinal range, so the browser moves under a frozen Python pin.
    """
    from camoufox_mcp.config import DEFAULT_BROWSER_VERSION

    monkeypatch.delenv("CAMOUFOX_BROWSER_VERSION", raising=False)
    assert _kwargs(data_dir, monkeypatch)["browser"] == DEFAULT_BROWSER_VERSION


@pytest.mark.parametrize("value", ["latest", "", "LATEST"])
def test_browser_pin_can_be_opted_out(
    value: str, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "browser" not in _kwargs(data_dir, monkeypatch, CAMOUFOX_BROWSER_VERSION=value)


def test_browser_pin_is_overridable(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _kwargs(data_dir, monkeypatch, CAMOUFOX_BROWSER_VERSION="135.0.1-beta.24")
    assert kwargs["browser"] == "135.0.1-beta.24"


def test_virtual_display_stays_linux_only(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Off Linux, 'virtual' is refused before anything is launched.

    Per-launch env isolation makes display modes safe to mix in one process, but it
    does not make Xvfb portable: Camoufox's own VirtualDisplay refuses to start
    anywhere but Linux, and we say so with a better message first.
    """
    from camoufox_mcp.sessions import launch

    monkeypatch.setattr(launch, "_IS_LINUX", False)
    with pytest.raises(ValueError, match="requires Linux"):
        _kwargs(data_dir, monkeypatch, CAMOUFOX_HEADLESS="virtual")
