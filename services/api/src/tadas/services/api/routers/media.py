"""Media: the org's files, as references to objects in the store.

A file; the parts of an upload the store does not hold yet, each signed for
a PUT straight to the store; the confirm once the parts are there; the link
a download follows straight from the store; and the org's storage used
(`/v1/media/files/{file_id}`, `.../upload`, `.../confirm`, `.../download`,
`/v1/media/usage`). No route takes or serves a file's bytes. Each function
is one call into the media service. A file is started by the namespace it
belongs to (a task's attachment by the task's route), never here."""

from uuid import UUID

from fastapi import APIRouter

from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.resolve import MediaService
from tadas.services.api.types.common import ErrorResponse
from tadas.services.api.types.media import (
    FileView,
    IssuedDownloadView,
    IssuedUploadView,
    StorageUsageView,
)

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/usage", response_model=StorageUsageView)
async def get_usage(ctx: Ctx, media: MediaService) -> StorageUsageView:
    return await media.get_usage(ctx)


@router.get("/files/{file_id}", response_model=FileView)
async def get_file(ctx: Ctx, media: MediaService, file_id: UUID) -> FileView:
    return await media.get_file(ctx, file_id)


@router.post("/files/{file_id}/upload", response_model=IssuedUploadView)
async def issue_upload(ctx: Ctx, media: MediaService, file_id: UUID) -> IssuedUploadView:
    """The parts the store does not hold yet. Asked again after an upload
    was cut off, it signs only the parts still missing, under the same
    upload."""
    return await media.issue_upload(ctx, file_id)


@router.post(
    "/files/{file_id}/confirm",
    response_model=FileView,
    responses={
        422: {
            "model": ErrorResponse,
            "description": "upload_refused: the parts the store holds do not sum to the size",
        },
    },
)
async def confirm_file(ctx: Ctx, media: MediaService, file_id: UUID) -> FileView:
    return await media.confirm_file(ctx, file_id)


@router.get("/files/{file_id}/download", response_model=IssuedDownloadView)
async def issue_download(
    ctx: Ctx, media: MediaService, file_id: UUID, inline: bool = False
) -> IssuedDownloadView:
    """`inline=true` is a preview the page shows; otherwise the link saves the
    file under its own name."""
    return await media.issue_download(ctx, file_id, inline)

