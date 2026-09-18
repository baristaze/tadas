"""Secrets: a capability, not a domain. The object model holds references;
the value is resolved at the point of use and discarded. Errors name the
secret and the store, never the value."""

from tadas.infra.exceptions import SecretNotFound, SecretsFileNotPrivate

__all__ = ["SecretNotFound", "SecretsFileNotPrivate", "SecretsInterface"]


class SecretsInterface:
    async def get(self, name: str) -> str:
        """Raises SecretNotFound."""
        ...

    async def has(self, name: str) -> bool: ...

    async def put(self, name: str, value: str) -> None: ...

    async def delete(self, name: str) -> None: ...

    def describe(self) -> str: ...

    async def start(self) -> None:
        """Opened by the infra root at boot. An impl that holds no connection
        of its own returns None."""
        ...

    async def close(self) -> None:
        """Closed by the infra root at shutdown, in reverse order of start."""
        ...
