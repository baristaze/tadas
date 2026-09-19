"""Secrets: a capability, not a domain. The object model holds references;
the value is resolved at the point of use and discarded. Errors name the
secret and the store, never the value."""

from abc import ABC, abstractmethod

from tadas.infra.exceptions import SecretNotFound, SecretsFileNotPrivate

__all__ = ["SecretNotFound", "SecretsFileNotPrivate", "SecretsInterface"]


class SecretsInterface(ABC):
    @abstractmethod
    async def get(self, name: str) -> str:
        """Raises SecretNotFound."""
        ...

    @abstractmethod
    async def has(self, name: str) -> bool: ...

    @abstractmethod
    async def put(self, name: str, value: str) -> None: ...

    @abstractmethod
    async def delete(self, name: str) -> None: ...

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
