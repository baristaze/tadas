"""The media service: what the wire can do with files, in views."""

from abc import ABC, abstractmethod
from uuid import UUID

from tadas.om.opcontext import OpContext
from tadas.services.api.types.media import (
    FileContentResponse,
    FileView,
    IssuedDownloadView,
    IssuedUploadView,
    StorageUsageView,
)


class MediaServiceInterface(ABC):
    @abstractmethod
    async def get_file(self, ctx: OpContext, file_id: UUID) -> FileView: ...

    @abstractmethod
    async def issue_upload(self, ctx: OpContext, file_id: UUID) -> IssuedUploadView: ...

    @abstractmethod
    async def put_content(self, ctx: OpContext, file_id: UUID, data: bytes) -> FileView: ...

    @abstractmethod
    async def confirm_file(self, ctx: OpContext, file_id: UUID) -> FileView: ...

    @abstractmethod
    async def issue_download(self, ctx: OpContext, file_id: UUID) -> IssuedDownloadView: ...

    @abstractmethod
    async def get_content(self, ctx: OpContext, file_id: UUID) -> FileContentResponse:
        """The bytes through the API, for a store that cannot sign a link."""
        ...

    @abstractmethod
    async def get_usage(self, ctx: OpContext) -> StorageUsageView: ...
