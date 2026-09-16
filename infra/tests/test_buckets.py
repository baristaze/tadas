from datetime import timedelta
from pathlib import Path

import pytest

from tadas.infra.buckets import BlobNotFound, Buckets
from tadas.infra.buckets.local import BucketsLocalImpl
from tadas.om.base import new_id
from tadas.om.exceptions import ValidationFailed


async def test_put_get_exists_list_delete(tmp_path: Path) -> None:
    buckets = BucketsLocalImpl(tmp_path)
    org = new_id()
    await buckets.put(org, Buckets.EXPORTS, "reports/a.csv", b"a,b", "text/csv")
    await buckets.put(org, Buckets.EXPORTS, "reports/b.csv", b"c,d", "text/csv")
    assert await buckets.exists(org, Buckets.EXPORTS, "reports/a.csv")
    assert await buckets.get(org, Buckets.EXPORTS, "reports/a.csv") == b"a,b"
    assert await buckets.list(org, Buckets.EXPORTS, "reports/") == [
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
    assert await buckets.list(org_b, Buckets.USER_FILE_UPLOADS, "") == []
    assert not await buckets.exists(org_b, Buckets.USER_FILE_UPLOADS, "x.bin")


async def test_keys_stay_inside_the_tenant_prefix(tmp_path: Path) -> None:
    buckets = BucketsLocalImpl(tmp_path)
    with pytest.raises(ValidationFailed):
        await buckets.put(new_id(), Buckets.EXPORTS, "../escape", b"", "text/plain")
    with pytest.raises(ValidationFailed):
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
