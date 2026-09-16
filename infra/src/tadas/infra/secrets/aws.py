from typing import Any

import aioboto3

from tadas.infra.aws_errors import ClientError, error_code, translated
from tadas.infra.secrets import SecretNotFound, SecretsInterface


class SecretsAwsImpl(SecretsInterface):
    """A client is opened per call, so this impl has no lifecycle of its own."""

    def __init__(self, session: aioboto3.Session, *, region: str, name_prefix: str) -> None:
        self._session = session
        self._region = region
        self._name_prefix = name_prefix

    def _client(self) -> Any:
        return self._session.client("secretsmanager", region_name=self._region)

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
        try:
            await self.get(name)
        except SecretNotFound:
            return False
        return True

    async def put(self, name: str, value: str) -> None:
        exists = await self.has(name)
        with translated("secretsmanager", "put"):
            async with self._client() as client:
                if exists:
                    await client.put_secret_value(SecretId=self._name(name), SecretString=value)
                else:
                    await client.create_secret(Name=self._name(name), SecretString=value)

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
