from uuid import UUID

from tadas.om.context import TenantContext
from tadas.om.media import MediaManagerInterface
from tadas.om.media.types.file import File
from tadas.services.api.services.media import MediaServiceInterface
from tadas.services.api.types.media import (
    FileView,
    IssuedDownloadView,
    IssuedPartView,
    IssuedUploadView,
    PurposeUsageView,
    StorageUsageView,
)


def file_view(file: File) -> FileView:
    return FileView.model_validate(file)


class MediaServiceImpl(MediaServiceInterface):
    def __init__(self, media: MediaManagerInterface) -> None:
        self._media = media

    async def get_file(self, ctx: TenantContext, file_id: UUID) -> FileView:
        return file_view(await self._media.get_file(ctx, file_id))

    async def issue_upload(self, ctx: TenantContext, file_id: UUID) -> IssuedUploadView:
        issued = await self._media.issue_upload(ctx, file_id)
        return IssuedUploadView(
            upload_id=issued.upload_id,
            parts=[IssuedPartView.model_validate(part) for part in issued.parts],
            remaining=issued.remaining,
            expires_at=issued.expires_at,
        )

    async def confirm_file(self, ctx: TenantContext, file_id: UUID) -> FileView:
        return file_view(await self._media.confirm_file(ctx, file_id))

    async def issue_download(
        self, ctx: TenantContext, file_id: UUID, inline: bool
    ) -> IssuedDownloadView:
        link = await self._media.issue_download(ctx, file_id, inline=inline)
        return IssuedDownloadView(url=link.url, expires_at=link.expires_at)

    async def get_usage(self, ctx: TenantContext) -> StorageUsageView:
        usage = await self._media.get_usage(ctx)
        return StorageUsageView(
            purposes=[PurposeUsageView.model_validate(p) for p in usage.purposes],
            total_count=usage.total_count,
            total_size_bytes=usage.total_size_bytes,
            pending_size_bytes=usage.pending_size_bytes,
        )
