from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _config(data_dir: Path, monkeypatch: pytest.MonkeyPatch, *, auto_update: str) -> object:
    monkeypatch.setenv("CAMOUFOX_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CAMOUFOX_HEADLESS", "true")
    monkeypatch.setenv("CAMOUFOX_AUTO_UPDATE", auto_update)
    from camoufox_mcp.config import ServerConfig

    return ServerConfig.from_env()


async def test_autoupdate_refreshes_once_then_throttles(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First start refreshes in the background; a start within 24h is throttled.

    This is the concurrency fix: the slow GitHub version check runs at most once
    per interval and never blocks the server from becoming ready, so many
    concurrent server starts don't each stall on it.
    """
    from camoufox_mcp import updater

    calls: list[str] = []
    monkeypatch.setattr(updater, "_update_browser", lambda: calls.append("browser"))
    monkeypatch.setattr(updater, "_update_geoip", lambda: calls.append("geoip"))
    config = _config(data_dir, monkeypatch, auto_update="true")

    task = updater.schedule_refresh(config)
    assert task is not None, "first start (no stamp) should schedule a refresh"
    await task
    assert calls == ["browser", "geoip"]
    assert updater._is_due(config) is False, "a fresh stamp should suppress the next check"

    assert updater.schedule_refresh(config) is None, "second start within 24h must be throttled"


async def test_autoupdate_disabled_never_schedules(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from camoufox_mcp import updater

    config = _config(data_dir, monkeypatch, auto_update="false")
    assert updater.schedule_refresh(config) is None
