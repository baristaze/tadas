"""The media service: what the wire can do with files, in views."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.context import TenantContext
from tadas.services.api.types.media import (
    FileContentResponse,
    FileView,
    IssuedDownloadView,
    IssuedUploadView,
    StorageUsageView,
)


class MediaServiceInterface(ABC):
    @abstractmethod
    async def get_file(self, ctx: TenantContext, file_id: UUID) -> FileView: ...

    @abstractmethod
    async def issue_upload(self, ctx: TenantContext, file_id: UUID) -> IssuedUploadView: ...

    @abstractmethod
    async def put_content(self, ctx: TenantContext, file_id: UUID, data: bytes) -> FileView: ...

    @abstractmethod
    async def confirm_file(self, ctx: TenantContext, file_id: UUID) -> FileView: ...

    @abstractmethod
    async def issue_download(
        self, ctx: TenantContext, file_id: UUID, inline: bool
    ) -> IssuedDownloadView: ...

    @abstractmethod
    async def get_content(
        self, ctx: TenantContext, file_id: UUID, inline: bool
    ) -> FileContentResponse:
        """The bytes through the API, for a store that cannot sign a link."""
        ...

    @abstractmethod
    async def get_usage(self, ctx: TenantContext) -> StorageUsageView: ...
