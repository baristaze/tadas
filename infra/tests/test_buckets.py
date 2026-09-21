import secrets
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import aioboto3
import pytest

from tadas.infra.base import new_id
from tadas.infra.buckets import BlobNotFound, Buckets, BucketsInterface
from tadas.infra.buckets.local import BucketsLocalImpl
from tadas.infra.buckets.s3 import BucketsS3Impl
from tadas.infra.exceptions import InvalidBucketKey
from tadas.infra.impl.settings import InfraSettings


async def test_put_get_exists_list_delete(tmp_path: Path) -> None:
    buckets = BucketsLocalImpl(tmp_path)
    org = new_id()
    await buckets.put(org, Buckets.EXPORTS, "reports/a.csv", b"a,b", "text/csv")
    await buckets.put(org, Buckets.EXPORTS, "reports/b.csv", b"c,d", "text/csv")
    assert await buckets.exists(org, Buckets.EXPORTS, "reports/a.csv")
    assert await buckets.get(org, Buckets.EXPORTS, "reports/a.csv") == b"a,b"
    assert await buckets.list(org, Buckets.EXPORTS, "reports/", limit=10) == [
        "reports/a.csv",
        "reports/b.csv",
    ]
    await buckets.delete(org, Buckets.EXPORTS, "reports/a.csv")
    assert not await buckets.exists(org, Buckets.EXPORTS, "reports/a.csv")
    with pytest.raises(BlobNotFound):
        await buckets.get(org, Buckets.EXPORTS, "reports/a.csv")


async def test_tenants_cannot_see_each_other(tmp_path: Path) -> None:
    buckets = BucketsLocalImpl(tmp_path)
    org_a, org_b = new_id(), new_id()
    await buckets.put(org_a, Buckets.USER_FILE_UPLOADS, "x.bin", b"1", "application/octet-stream")
    assert await buckets.list(org_b, Buckets.USER_FILE_UPLOADS, "", limit=10) == []
    assert not await buckets.exists(org_b, Buckets.USER_FILE_UPLOADS, "x.bin")


async def test_keys_stay_inside_the_tenant_prefix(tmp_path: Path) -> None:
    buckets = BucketsLocalImpl(tmp_path)
    with pytest.raises(InvalidBucketKey):
        await buckets.put(new_id(), Buckets.EXPORTS, "../escape", b"", "text/plain")
    with pytest.raises(InvalidBucketKey):
        await buckets.get(new_id(), Buckets.EXPORTS, "/absolute")


async def test_local_impl_cannot_presign(tmp_path: Path) -> None:
    buckets = BucketsLocalImpl(tmp_path)
    assert await buckets.presign_get(new_id(), Buckets.EXPORTS, "k", timedelta(minutes=1)) is None
    assert (
        await buckets.presign_put(
            new_id(), Buckets.EXPORTS, "k", "text/plain", timedelta(minutes=1)
        )
        is None
    )


async def listing_is_bounded_lexical_and_resumes_after(buckets: BucketsInterface) -> None:
    """The listing contract every impl meets: keys in lexical order, at most
    `limit` of them, and the next page starting after the last key returned.
    The S3 impl runs it over the compose stack's MinIO in the integration
    suite, below."""
    org, other = new_id(), new_id()
    keys = ["r/b", "r/a", "r/c/1", "r/c/2", "r/d", "s/x"]
    for key in keys:
        await buckets.put(org, Buckets.EXPORTS, key, b"x", "text/plain")
    await buckets.put(other, Buckets.EXPORTS, "r/a0", b"x", "text/plain")
    every = sorted(k for k in keys if k.startswith("r/"))
    assert await buckets.list(org, Buckets.EXPORTS, "r/", limit=100) == every
    assert await buckets.list(org, Buckets.EXPORTS, "r/", limit=2) == every[:2]
    pages: list[str] = []
    after: str | None = None
    while page := await buckets.list(org, Buckets.EXPORTS, "r/", limit=2, after=after):
        assert len(page) <= 2
        pages.extend(page)
        after = page[-1]
    assert pages == every
    assert await buckets.list(org, Buckets.EXPORTS, "r/", limit=10, after="r/c") == every[2:]
    assert await buckets.list(org, Buckets.EXPORTS, "r/", limit=10, after="r/d") == []


async def test_the_local_listing_is_bounded_and_resumes(tmp_path: Path) -> None:
    await listing_is_bounded_lexical_and_resumes_after(BucketsLocalImpl(tmp_path))


@pytest.fixture
async def s3_buckets() -> AsyncIterator[BucketsS3Impl]:
    """The S3 impl over the compose stack's MinIO, on a bucket of its own that
    is emptied and removed afterwards."""
    settings = InfraSettings()
    session = aioboto3.Session(
        aws_access_key_id=settings.s3_access_key or "tadas",
        aws_secret_access_key=settings.s3_secret_key or "tadastadas",
        region_name=settings.aws_region,
    )
    endpoint = settings.s3_endpoint_url or "http://127.0.0.1:59000"
    prefix = f"tadas-it-{secrets.token_hex(4)}"
    name = f"{prefix}-{Buckets.EXPORTS.value}"
    admin: Any = session.client("s3", endpoint_url=endpoint)
    async with admin as s3:
        await s3.create_bucket(Bucket=name)
    impl = BucketsS3Impl(
        session,
        endpoint_url=endpoint,
        region=settings.aws_region,
        bucket_prefix=prefix,
        timeout=timedelta(seconds=10),
    )
    await impl.start()
    try:
        yield impl
    finally:
        await impl.close()
        cleanup: Any = session.client("s3", endpoint_url=endpoint)
        async with cleanup as s3:
            listed = await s3.list_objects_v2(Bucket=name)
            for item in listed.get("Contents", []):
                await s3.delete_object(Bucket=name, Key=item["Key"])
            await s3.delete_bucket(Bucket=name)


@pytest.mark.integration
async def test_the_s3_listing_is_bounded_and_resumes(s3_buckets: BucketsS3Impl) -> None:
    await listing_is_bounded_lexical_and_resumes_after(s3_buckets)


@pytest.mark.integration
async def test_an_s3_limit_past_one_call_continues_within_itself(
    s3_buckets: BucketsS3Impl, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tadas.infra.buckets.s3.MAX_KEYS_PER_CALL", 2)
    org = new_id()
    keys = [f"k/{i}" for i in range(5)]
    for key in keys:
        await s3_buckets.put(org, Buckets.EXPORTS, key, b"x", "text/plain")
    assert await s3_buckets.list(org, Buckets.EXPORTS, "k/", limit=4) == keys[:4]
    assert await s3_buckets.list(org, Buckets.EXPORTS, "k/", limit=10, after="k/0") == keys[1:]
