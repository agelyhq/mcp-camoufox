from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import zipfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.browser.config import S3Config

logger = logging.getLogger(__name__)

_S3_KEY_TEMPLATE = "profiles/{name}.zip"


def _s3_key(name: str) -> str:
    return _S3_KEY_TEMPLATE.format(name=name)


def _make_client(cfg: S3Config) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        region_name=cfg.region,
    )


def _zip_dir_sync(source: Path, dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in source.rglob("*"):
            with contextlib.suppress(FileNotFoundError, OSError):
                zf.write(file, file.relative_to(source))


def _unzip_sync(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)


def _download_sync(cfg: S3Config, name: str, dest: Path) -> bool:
    """Download profile zip from S3. Returns True if found, False if not exists."""
    from botocore.exceptions import ClientError

    client = _make_client(cfg)
    key = _s3_key(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(cfg.bucket, key, str(dest))
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey"):
            return False
        raise


def _upload_sync(cfg: S3Config, name: str, archive: Path) -> None:
    client = _make_client(cfg)
    key = _s3_key(name)
    with archive.open("rb") as f:
        client.put_object(Bucket=cfg.bucket, Key=key, Body=f)


async def pull_profile(cfg: S3Config, name: str, profiles_dir: Path) -> Path:
    """Download and unzip a profile from S3. Creates empty dir if not found.

    Returns the local profile directory path.
    """
    profile_dir = profiles_dir / name
    archive = profiles_dir / f"{name}.zip"

    try:
        found = await asyncio.to_thread(_download_sync, cfg, name, archive)
        if found:
            logger.info("Profile %r downloaded from S3, extracting…", name)
            if profile_dir.exists():
                shutil.rmtree(profile_dir)
            await asyncio.to_thread(_unzip_sync, archive, profile_dir)
            archive.unlink(missing_ok=True)
            logger.info("Profile %r ready at %s", name, profile_dir)
        else:
            logger.info("Profile %r not found on S3, starting fresh", name)
            profile_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning("S3 pull failed for profile %r, using local/empty", name, exc_info=True)
        archive.unlink(missing_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)

    return profile_dir


async def push_profile(cfg: S3Config, name: str, tmpdir: Path) -> None:
    """Zip profile from tmpdir and upload to S3."""
    profile_dir = tmpdir / name
    if not profile_dir.exists():
        logger.warning("Profile dir %s does not exist, skipping push", profile_dir)
        return

    archive = tmpdir / f"{name}.zip"
    try:
        await asyncio.to_thread(_zip_dir_sync, profile_dir, archive)
        await asyncio.to_thread(_upload_sync, cfg, name, archive)
        logger.info("Profile %r uploaded to S3", name)
    except Exception:
        logger.warning("S3 push failed for profile %r", name, exc_info=True)
    finally:
        archive.unlink(missing_ok=True)
