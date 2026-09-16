from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from tadas.infra.secrets import SecretNotFound, SecretsInterface


class SecretsAwsImpl(SecretsInterface):
    def __init__(self, session: aioboto3.Session, *, region: str, name_prefix: str) -> None:
        self._session = session
        self._region = region
        self._name_prefix = name_prefix

    def _client(self) -> Any:
        return self._session.client("secretsmanager", region_name=self._region)

    def _name(self, name: str) -> str:
        return f"{self._name_prefix}{name}"

    async def get(self, name: str) -> str:
        async with self._client() as client:
            try:
                response = await client.get_secret_value(SecretId=self._name(name))
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
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
        async with self._client() as client:
            if await self.has(name):
                await client.put_secret_value(SecretId=self._name(name), SecretString=value)
            else:
                await client.create_secret(Name=self._name(name), SecretString=value)

    async def delete(self, name: str) -> None:
        async with self._client() as client:
            await client.delete_secret(SecretId=self._name(name), ForceDeleteWithoutRecovery=True)

    def describe(self) -> str:
        return f"secrets=aws({self._region})"
