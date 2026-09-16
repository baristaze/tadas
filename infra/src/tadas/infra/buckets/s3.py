from datetime import timedelta
from typing import Any
from uuid import UUID

import aioboto3
from botocore.exceptions import ClientError

from tadas.infra.buckets import BlobNotFound, Buckets, BucketsInterface, object_key


class BucketsS3Impl(BucketsInterface):
    def __init__(
        self,
        session: aioboto3.Session,
        *,
        endpoint_url: str | None,
        region: str,
        bucket_prefix: str,
    ) -> None:
        self._session = session
        self._endpoint_url = endpoint_url
        self._region = region
        self._bucket_prefix = bucket_prefix

    def _client(self) -> Any:
        return self._session.client("s3", endpoint_url=self._endpoint_url, region_name=self._region)

    def _bucket(self, bucket: Buckets) -> str:
        return f"{self._bucket_prefix}-{bucket.value}"

    async def put(
        self, org_id: UUID, bucket: Buckets, key: str, data: bytes, content_type: str
    ) -> None:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket(bucket),
                Key=object_key(org_id, key),
                Body=data,
                ContentType=content_type,
            )

    async def get(self, org_id: UUID, bucket: Buckets, key: str) -> bytes:
        async with self._client() as s3:
            try:
                response = await s3.get_object(
                    Bucket=self._bucket(bucket), Key=object_key(org_id, key)
                )
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                    raise BlobNotFound(f"{bucket.value}/{key}") from None
                raise
            async with response["Body"] as body:
                return await body.read()

    async def exists(self, org_id: UUID, bucket: Buckets, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket(bucket), Key=object_key(org_id, key))
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise
            return True

    async def list(self, org_id: UUID, bucket: Buckets, prefix: str) -> list[str]:
        tenant_prefix = f"{org_id}/"
        keys: list[str] = []
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=self._bucket(bucket), Prefix=tenant_prefix + prefix
            ):
                for item in page.get("Contents", []):
                    keys.append(item["Key"][len(tenant_prefix) :])
        return sorted(keys)

    async def delete(self, org_id: UUID, bucket: Buckets, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket(bucket), Key=object_key(org_id, key))

    async def presign_get(
        self, org_id: UUID, bucket: Buckets, key: str, ttl: timedelta
    ) -> str | None:
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket(bucket), "Key": object_key(org_id, key)},
                ExpiresIn=int(ttl.total_seconds()),
            )

    async def presign_put(
        self, org_id: UUID, bucket: Buckets, key: str, content_type: str, ttl: timedelta
    ) -> str | None:
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket(bucket),
                    "Key": object_key(org_id, key),
                    "ContentType": content_type,
                },
                ExpiresIn=int(ttl.total_seconds()),
            )

    def describe(self) -> str:
        return f"buckets=s3({self._endpoint_url or self._region})"
