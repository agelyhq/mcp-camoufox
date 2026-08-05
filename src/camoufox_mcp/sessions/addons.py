from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# Per-socket-operation deadline on an addon download. Without one, a host that accepts
# the connection and then says nothing holds the download thread forever, and with it
# the session creation that awaits it: in daemon mode that is one unreachable addon
# host against every client the process serves. A timeout is not fatal here, it is the
# per-addon warning below, and the browser launches without that addon.
DOWNLOAD_TIMEOUT = 30.0


def _url_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _download_sync(url: str, dest: Path) -> None:
    """Fetch one XPI to ``dest``, under a deadline, and only ever whole.

    The bytes land in a sibling ``.part`` file and are renamed into place at the end,
    so an interrupted download cannot leave a truncated archive that every later run
    would find in the cache and trust.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f"{dest.name}.part")
    try:
        with urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)


def _extract_xpi(xpi_path: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    with zipfile.ZipFile(xpi_path) as zf:
        zf.extractall(dest_dir)


async def prepare_addons(
    urls: tuple[str, ...],
    *,
    cache_dir: Path,
) -> tuple[list[str], Path | None]:
    """Download (cached in ``cache_dir``) and extract addons. Returns (addon_dirs, temp_root)."""
    if not urls:
        return [], None

    tmp = Path(tempfile.mkdtemp(prefix="camoufox-addons-"))
    addon_dirs: list[str] = []

    for url in urls:
        key = _url_cache_key(url)
        xpi_path = cache_dir / f"{key}.xpi"

        try:
            if not xpi_path.exists():
                logger.info("Downloading addon: %s", url)
                await asyncio.to_thread(_download_sync, url, xpi_path)

            extract_dir = tmp / key
            await asyncio.to_thread(_extract_xpi, xpi_path, extract_dir)
            addon_dirs.append(str(extract_dir))
        except Exception:
            logger.warning("Failed to load addon %s", url, exc_info=True)

    return addon_dirs, tmp


def cleanup_addons(tmp_dir: Path | None) -> None:
    if tmp_dir and tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
