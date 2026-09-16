"""Secrets: a capability, not a domain. The object model holds references;
the value is resolved at the point of use and discarded. Errors name the
secret and the store, never the value."""

from tadas.om.exceptions import NotFound, PlatformException


class SecretNotFound(NotFound):
    code = "secret_not_found"

    def __init__(self, name: str, store: str) -> None:
        super().__init__(f"secret {name!r} not found in {store}")


class SecretsFileNotPrivate(PlatformException):
    code = "secrets_file_not_private"


class SecretsInterface:
    async def get(self, name: str) -> str:
        """Raises SecretNotFound."""
        ...

    async def has(self, name: str) -> bool: ...

    async def put(self, name: str, value: str) -> None: ...

    async def delete(self, name: str) -> None: ...

    def describe(self) -> str: ...
