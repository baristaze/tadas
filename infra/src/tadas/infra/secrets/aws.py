from datetime import timedelta
from typing import Any

import aioboto3

from tadas.infra.aws_clients import client_config
from tadas.infra.aws_errors import ClientError, error_code, translated
from tadas.infra.secrets import SecretNotFound, SecretsInterface


class SecretsAwsImpl(SecretsInterface):
    """A client is opened per call, so this impl has no lifecycle of its own."""

    def __init__(
        self, session: aioboto3.Session, *, region: str, name_prefix: str, timeout: timedelta
    ) -> None:
        self._session = session
        self._region = region
        self._name_prefix = name_prefix
        self._config = client_config(timeout)

    def _client(self) -> Any:
        return self._session.client("secretsmanager", region_name=self._region, config=self._config)

    def _name(self, name: str) -> str:
        return f"{self._name_prefix}{name}"

    async def get(self, name: str) -> str:
        with translated("secretsmanager", "get"):
            async with self._client() as client:
                try:
                    response = await client.get_secret_value(SecretId=self._name(name))
                except ClientError as error:
                    if error_code(error) == "ResourceNotFoundException":
                        raise SecretNotFound(name, "aws secrets manager") from None
                    raise
        return response["SecretString"]

    async def has(self, name: str) -> bool:
        """Existence is metadata: the value never leaves the store for a
        question that does not need it."""
        with translated("secretsmanager", "has"):
            async with self._client() as client:
                try:
                    await client.describe_secret(SecretId=self._name(name))
                except ClientError as error:
                    if error_code(error) == "ResourceNotFoundException":
                        return False
                    raise
        return True

    async def put(self, name: str, value: str) -> None:
        """Create, and on the store saying it exists, write a new version:
        one call in the common case and no window between a read and a
        write for another writer to slip into."""
        with translated("secretsmanager", "put"):
            async with self._client() as client:
                try:
                    await client.create_secret(Name=self._name(name), SecretString=value)
                except ClientError as error:
                    if error_code(error) != "ResourceExistsException":
                        raise
                    await client.put_secret_value(SecretId=self._name(name), SecretString=value)

    async def delete(self, name: str) -> None:
        with translated("secretsmanager", "delete"):
            async with self._client() as client:
                await client.delete_secret(
                    SecretId=self._name(name), ForceDeleteWithoutRecovery=True
                )

    def describe(self) -> str:
        return f"secrets=aws({self._region})"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
