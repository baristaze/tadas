from datetime import timedelta
from typing import Any

import aioboto3

from tadas.infra.aws_clients import AwsClientHolder, client_config
from tadas.infra.aws_errors import ClientError, error_code, translated
from tadas.infra.secrets import SecretNotFound, SecretsInterface


class SecretsAwsImpl(SecretsInterface):
    """One client, opened at start() and closed at close()."""

    def __init__(
        self, session: aioboto3.Session, *, region: str, name_prefix: str, timeout: timedelta
    ) -> None:
        self._name_prefix = name_prefix
        self._region = region
        config = client_config(timeout)
        self._holder = AwsClientHolder(
            "secretsmanager",
            lambda: session.client("secretsmanager", region_name=region, config=config),
        )

    def _client(self) -> Any:
        return self._holder.client()

    def _name(self, name: str) -> str:
        return f"{self._name_prefix}{name}"

    async def get(self, name: str) -> str:
        with translated("secretsmanager", "get"):
            try:
                response = await self._client().get_secret_value(SecretId=self._name(name))
            except ClientError as error:
                if error_code(error) == "ResourceNotFoundException":
                    raise SecretNotFound(name, "aws secrets manager") from None
                raise
        return response["SecretString"]

    async def has(self, name: str) -> bool:
        """Existence is metadata: the value never leaves the store for a
        question that does not need it."""
        with translated("secretsmanager", "has"):
            try:
                await self._client().describe_secret(SecretId=self._name(name))
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
            client = self._client()
            try:
                await client.create_secret(Name=self._name(name), SecretString=value)
            except ClientError as error:
                if error_code(error) != "ResourceExistsException":
                    raise
                await client.put_secret_value(SecretId=self._name(name), SecretString=value)

    async def delete(self, name: str) -> None:
        with translated("secretsmanager", "delete"):
            await self._client().delete_secret(
                SecretId=self._name(name), ForceDeleteWithoutRecovery=True
            )

    def describe(self) -> str:
        return f"secrets=aws({self._region})"

    async def start(self) -> None:
        await self._holder.open()

    async def close(self) -> None:
        await self._holder.close()
