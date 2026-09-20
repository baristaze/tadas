"""The hosted secrets impl asks the store only what it needs: existence is
a describe, never a fetch of the value; a put is a create, and a new version
only when the store says the secret exists."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from tadas.infra.exceptions import BackendFailed
from tadas.infra.secrets.aws import SecretsAwsImpl


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "from the driver"}}, "Op")


class RecordingClient:
    """A store with some secrets in it, recording every call by name."""

    def __init__(self, existing: set[str], describe_fails_with: str | None = None) -> None:
        self.existing = existing
        self.calls: list[tuple[str, str]] = []
        self._describe_fails_with = describe_fails_with

    async def describe_secret(self, **request: str) -> dict[str, Any]:
        name = request["SecretId"]
        self.calls.append(("describe_secret", name))
        if self._describe_fails_with:
            raise client_error(self._describe_fails_with)
        if name not in self.existing:
            raise client_error("ResourceNotFoundException")
        return {"Name": name}

    async def get_secret_value(self, **request: str) -> dict[str, Any]:
        name = request["SecretId"]
        self.calls.append(("get_secret_value", name))
        if name not in self.existing:
            raise client_error("ResourceNotFoundException")
        return {"SecretString": "the value"}

    async def create_secret(self, **request: str) -> dict[str, Any]:
        name = request["Name"]
        self.calls.append(("create_secret", name))
        if name in self.existing:
            raise client_error("ResourceExistsException")
        self.existing.add(name)
        return {"Name": name}

    async def put_secret_value(self, **request: str) -> dict[str, Any]:
        name = request["SecretId"]
        self.calls.append(("put_secret_value", name))
        assert name in self.existing
        return {"Name": name}


class FakeSession:
    def __init__(self, client: RecordingClient) -> None:
        self.recording = client

    def client(self, *args: Any, **kwargs: Any) -> Any:
        @asynccontextmanager
        async def open_client() -> AsyncIterator[Any]:
            yield self.recording

        return open_client()


def secrets(client: RecordingClient) -> SecretsAwsImpl:
    return SecretsAwsImpl(
        FakeSession(client),  # type: ignore[arg-type]
        region="us-east-1",
        name_prefix="tadas/",
        timeout=timedelta(seconds=1),
    )


async def test_has_describes_and_never_fetches_the_value() -> None:
    store = RecordingClient({"tadas/present"})
    impl = secrets(store)
    assert await impl.has("present") is True
    assert await impl.has("absent") is False
    assert store.calls == [
        ("describe_secret", "tadas/present"),
        ("describe_secret", "tadas/absent"),
    ]


async def test_put_creates_and_falls_back_to_a_new_version() -> None:
    store = RecordingClient({"tadas/present"})
    impl = secrets(store)
    await impl.put("fresh", "v1")
    await impl.put("present", "v2")
    assert store.calls == [
        ("create_secret", "tadas/fresh"),
        ("create_secret", "tadas/present"),
        ("put_secret_value", "tadas/present"),
    ]


async def test_any_other_answer_to_has_is_a_backend_failure() -> None:
    with pytest.raises(BackendFailed) as raised:
        await secrets(RecordingClient(set(), describe_fails_with="AccessDeniedException")).has("x")
    assert raised.value.message == "secretsmanager has failed with AccessDeniedException"
