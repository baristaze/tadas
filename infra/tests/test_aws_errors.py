"""The hosted impls never let the driver's error type cross the boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from botocore.exceptions import ClientError

from tadas.infra.buckets import BlobNotFound, Buckets
from tadas.infra.buckets.s3 import BucketsS3Impl
from tadas.infra.exceptions import BackendFailed, InfraException
from tadas.infra.secrets import SecretNotFound
from tadas.infra.secrets.aws import SecretsAwsImpl
from tadas.om.base import new_id
from tadas.om.exceptions import PlatformException


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "from the driver"}}, "Op")


class FailingPaginator:
    def __init__(self, code: str) -> None:
        self._code = code

    async def paginate(self, **kwargs: Any) -> AsyncIterator[Any]:
        raise client_error(self._code)
        yield  # pragma: no cover


class FailingClient:
    """Every operation, paginated or not, raises the configured code."""

    def __init__(self, code: str) -> None:
        self._code = code

    def get_paginator(self, name: str) -> FailingPaginator:
        return FailingPaginator(self._code)

    def __getattr__(self, name: str) -> Any:
        async def operation(*args: Any, **kwargs: Any) -> Any:
            raise client_error(self._code)

        return operation


class FakeSession:
    def __init__(self, code: str) -> None:
        self._code = code

    def client(self, *args: Any, **kwargs: Any) -> Any:
        @asynccontextmanager
        async def open_client() -> AsyncIterator[Any]:
            yield FailingClient(self._code)

        return open_client()


def buckets(code: str) -> BucketsS3Impl:
    return BucketsS3Impl(
        FakeSession(code),  # type: ignore[arg-type]
        endpoint_url=None,
        region="us-east-1",
        bucket_prefix="tadas",
    )


def secrets(code: str) -> SecretsAwsImpl:
    return SecretsAwsImpl(FakeSession(code), region="us-east-1", name_prefix="tadas/")  # type: ignore[arg-type]


async def test_not_found_codes_keep_their_shape() -> None:
    with pytest.raises(BlobNotFound):
        await buckets("NoSuchKey").get(new_id(), Buckets.EXPORTS, "k")
    assert await buckets("404").exists(new_id(), Buckets.EXPORTS, "k") is False
    with pytest.raises(SecretNotFound):
        await secrets("ResourceNotFoundException").get("token")
    assert await secrets("ResourceNotFoundException").has("token") is False


async def test_every_other_code_becomes_a_platform_exception() -> None:
    with pytest.raises(BackendFailed) as raised:
        await buckets("AccessDenied").get(new_id(), Buckets.EXPORTS, "k")
    assert isinstance(raised.value, InfraException)
    assert isinstance(raised.value, PlatformException)
    assert raised.value.message == "s3 get failed with AccessDenied"
    with pytest.raises(BackendFailed):
        await buckets("SlowDown").put(new_id(), Buckets.EXPORTS, "k", b"", "text/plain")
    with pytest.raises(BackendFailed):
        await buckets("AccessDenied").list(new_id(), Buckets.EXPORTS, "")
    with pytest.raises(BackendFailed) as raised:
        await secrets("AccessDeniedException").get("token")
    assert "from the driver" not in raised.value.message
    with pytest.raises(BackendFailed):
        await secrets("AccessDeniedException").delete("token")
