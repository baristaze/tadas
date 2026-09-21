"""Buckets: large blobs. Every call takes org_id and the impl prefixes keys
with it, so one tenant's blobs cannot be read or listed by another."""

from abc import ABC, abstractmethod
from datetime import timedelta
from enum import Enum
from uuid import UUID

from tadas.infra.exceptions import BlobNotFound, InvalidBucketKey

__all__ = ["BlobNotFound", "Buckets", "BucketsInterface", "InvalidBucketKey", "object_key"]


class Buckets(str, Enum):
    USER_FILE_UPLOADS = "user-file-uploads"
    EXPORTS = "exports"


def object_key(org_id: UUID, key: str) -> str:
    """The storage key: the tenant first, then the caller's path."""
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise InvalidBucketKey(f"bucket key {key!r} is not a relative path")
    return f"{org_id}/{key}"


class BucketsInterface(ABC):
    @abstractmethod
    async def put(
        self, org_id: UUID, bucket: Buckets, key: str, data: bytes, content_type: str
    ) -> None: ...

    @abstractmethod
    async def get(self, org_id: UUID, bucket: Buckets, key: str) -> bytes: ...

    @abstractmethod
    async def exists(self, org_id: UUID, bucket: Buckets, key: str) -> bool: ...

    @abstractmethod
    async def list(
        self, org_id: UUID, bucket: Buckets, prefix: str, limit: int, after: str | None = None
    ) -> list[str]:
        """The tenant's keys under `prefix`, in lexical order, at most `limit`
        of them, strictly after `after` when one is given. The next page
        starts after the last key returned. The caller picks the bound."""
        ...

    @abstractmethod
    async def delete(self, org_id: UUID, bucket: Buckets, key: str) -> None: ...

    @abstractmethod
    async def presign_get(
        self, org_id: UUID, bucket: Buckets, key: str, ttl: timedelta
    ) -> str | None: ...

    @abstractmethod
    async def presign_put(
        self, org_id: UUID, bucket: Buckets, key: str, content_type: str, ttl: timedelta
    ) -> str | None: ...

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    async def start(self) -> None:
        """Opened by the infra root at boot. An impl that holds no connection
        of its own returns None."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Closed by the infra root at shutdown, in reverse order of start."""
        ...
