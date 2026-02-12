from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

DEFAULT_ADDON_URLS: tuple[str, ...] = (
    "https://addons.mozilla.org/firefox/downloads/latest/istilldontcareaboutcookies/latest.xpi",
)

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "camoufox-mcp" / "addons"


def _url_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _download_sync(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, dest)


def _extract_xpi(xpi_path: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    with zipfile.ZipFile(xpi_path) as zf:
        zf.extractall(dest_dir)


async def prepare_addons(
    urls: tuple[str, ...],
    cache_dir: Path = _DEFAULT_CACHE_DIR,
) -> tuple[list[str], Path | None]:
    """Download (cached) and extract addons. Returns (addon_dirs, temp_root)."""
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
