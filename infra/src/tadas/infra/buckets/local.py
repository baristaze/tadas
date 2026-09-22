import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from tadas.infra.buckets import BlobNotFound, Buckets, BucketsInterface, PresignedUpload, object_key


class BucketsLocalImpl(BucketsInterface):
    """A filesystem impl with the same layout as the object store. It cannot
    presign, so both presign calls return None and the caller proxies."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, org_id: UUID, bucket: Buckets, key: str) -> Path:
        return self._root / bucket.value / object_key(org_id, key)

    async def put(
        self, org_id: UUID, bucket: Buckets, key: str, data: bytes, content_type: str
    ) -> None:
        path = self._path(org_id, bucket, key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.with_name(path.name + ".content-type").write_text(content_type)

        await asyncio.to_thread(write)

    async def get(self, org_id: UUID, bucket: Buckets, key: str) -> bytes:
        path = self._path(org_id, bucket, key)
        if not await asyncio.to_thread(path.is_file):
            raise BlobNotFound(f"{bucket.value}/{key}")
        return await asyncio.to_thread(path.read_bytes)

    async def exists(self, org_id: UUID, bucket: Buckets, key: str) -> bool:
        return await asyncio.to_thread(self._path(org_id, bucket, key).is_file)

    async def list(
        self, org_id: UUID, bucket: Buckets, prefix: str, limit: int, after: str | None = None
    ) -> list[str]:
        base = self._root / bucket.value / str(org_id)

        def walk() -> list[str]:
            if not base.is_dir():
                return []
            keys = [
                p.relative_to(base).as_posix()
                for p in base.rglob("*")
                if p.is_file() and not p.name.endswith(".content-type")
            ]
            # Code-point order, which is the byte order of the object store's
            # UTF-8 keys; a filesystem has no listing that stops early, so the
            # walk is whole and the answer is bounded.
            listed = sorted(
                k for k in keys if k.startswith(prefix) and (after is None or k > after)
            )
            return listed[:limit]

        return await asyncio.to_thread(walk)

    async def delete(self, org_id: UUID, bucket: Buckets, key: str) -> None:
        path = self._path(org_id, bucket, key)

        def remove() -> None:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".content-type").unlink(missing_ok=True)

        await asyncio.to_thread(remove)

    async def presign_get(
        self, org_id: UUID, bucket: Buckets, key: str, ttl: timedelta
    ) -> str | None:
        return None

    async def presign_upload(
        self,
        org_id: UUID,
        bucket: Buckets,
        key: str,
        content_type: str,
        max_bytes: int,
        ttl: timedelta,
    ) -> PresignedUpload | None:
        return None

    def describe(self) -> str:
        return f"buckets=local({self._root})"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
