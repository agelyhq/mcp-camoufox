from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import boto3
import pytest

from camoufox_mcp.browser.config import S3Config
from camoufox_mcp.browser.profile_store import pull_profile, push_profile

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_BUCKET = "test-profiles-unit"
_ENDPOINT = "http://127.0.0.1:5124"


@pytest.fixture
def s3_cfg() -> S3Config:
    return S3Config(
        endpoint_url=_ENDPOINT,
        access_key="test",
        secret_key="test",
        bucket=_BUCKET,
    )


@pytest.fixture
def tmpdir(tmp_path: Path) -> Path:
    return tmp_path / "profiles"


@pytest.fixture(autouse=True)
def _fresh_bucket() -> Iterator[None]:
    """Each test gets a clean bucket (delete+recreate) on the shared moto server."""
    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=_ENDPOINT)
    try:
        objs = s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])
        for obj in objs:
            s3.delete_object(Bucket=_BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=_BUCKET)
    except Exception:
        pass
    s3.create_bucket(Bucket=_BUCKET)
    yield


async def test_pull_profile_not_found_creates_empty_dir(s3_cfg: S3Config, tmpdir: Path) -> None:
    """When object doesn't exist on S3, pull_profile creates an empty local dir."""
    result = await pull_profile(s3_cfg, "newprofile", tmpdir)

    assert result.is_dir()
    assert result == tmpdir / "newprofile"
    assert list(result.iterdir()) == []


async def test_pull_profile_found_extracts_zip(s3_cfg: S3Config, tmpdir: Path) -> None:
    """When a zip exists on S3, pull_profile downloads and extracts it."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    archive = tmpdir / "seed.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Cookies", "fake-cookie-data")

    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=_ENDPOINT)
    s3.upload_file(str(archive), _BUCKET, "profiles/existing.zip")
    archive.unlink()

    result = await pull_profile(s3_cfg, "existing", tmpdir)

    assert result.is_dir()
    assert (result / "Cookies").read_text() == "fake-cookie-data"
    assert not (tmpdir / "existing.zip").exists()


async def test_push_profile_zips_and_uploads(s3_cfg: S3Config, tmpdir: Path) -> None:
    """push_profile zips and uploads to S3; local profile dir remains (caller cleans up)."""
    profile_dir = tmpdir / "mypro"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Cookies").write_text("cookie-content")

    await push_profile(s3_cfg, "mypro", tmpdir)

    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=_ENDPOINT)
    objs = s3.list_objects_v2(Bucket=_BUCKET, Prefix="profiles/mypro.zip")
    assert objs.get("KeyCount", 0) == 1, "Expected zip uploaded to S3"

    assert profile_dir.exists()
    assert not (tmpdir / "mypro.zip").exists()


async def test_push_then_pull_roundtrip(s3_cfg: S3Config, tmpdir: Path) -> None:
    """push then pull must restore the same profile content."""
    profile_dir = tmpdir / "round"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Cookies").write_text("my-cookies")

    await push_profile(s3_cfg, "round", tmpdir)

    restore_dir = tmpdir / "restore"
    result = await pull_profile(s3_cfg, "round", restore_dir)

    assert (result / "Cookies").read_text() == "my-cookies"


async def test_push_profile_missing_dir_is_noop(s3_cfg: S3Config, tmpdir: Path) -> None:
    """push_profile on a non-existent directory must not raise and upload nothing."""
    await push_profile(s3_cfg, "ghost", tmpdir)

    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=_ENDPOINT)
    objs = s3.list_objects_v2(Bucket=_BUCKET)
    assert objs.get("KeyCount", 0) == 0
