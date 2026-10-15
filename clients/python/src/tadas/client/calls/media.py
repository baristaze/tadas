"""The media namespace's calls: the org's files, as references to objects in
the store."""

from typing import cast
from uuid import UUID

import httpx

from tadas.client.transport import ApiError, Transport, trust_store
from tadas.client.types.media import (
    FileView,
    IssuedDownloadView,
    IssuedUploadView,
    StorageUsageView,
)


class MediaCalls(Transport):
    """Uploads, files, downloads, and the org's storage."""

    async def file(self, file_id: UUID) -> FileView:
        return FileView.model_validate(await self.request("GET", f"/v1/media/files/{file_id}"))

    async def issue_upload(self, file_id: UUID) -> IssuedUploadView:
        form = await self.request("POST", f"/v1/media/files/{file_id}/upload")
        return IssuedUploadView.model_validate(form)

    async def put_content(self, file_id: UUID, data: bytes) -> FileView:
        """The bytes through the API, for a store that cannot take a form post."""
        put = await self.request("PUT", f"/v1/media/files/{file_id}/content", content=data)
        return FileView.model_validate(put)

    async def confirm_file(self, file_id: UUID) -> FileView:
        return FileView.model_validate(
            await self.request("POST", f"/v1/media/files/{file_id}/confirm")
        )

    async def issue_download(self, file_id: UUID) -> IssuedDownloadView:
        link = await self.request("GET", f"/v1/media/files/{file_id}/download")
        return IssuedDownloadView.model_validate(link)

    async def content(self, file_id: UUID) -> bytes:
        return cast(
            bytes, await self.request("GET", f"/v1/media/files/{file_id}/content", raw=True)
        )

    async def storage_usage(self) -> StorageUsageView:
        return StorageUsageView.model_validate(await self.request("GET", "/v1/media/usage"))

    async def upload(self, started: FileView, data: bytes) -> FileView:
        """The bytes of a started upload, then its confirm. They go straight to
        the store with the form the API signed, or through the API when the
        store cannot take a post. The post to the store carries no credential
        of ours: the form is the credential, and it holds the post to this
        file's type and size."""
        form = await self.issue_upload(started.id)
        if form.url is None:
            await self.put_content(started.id, data)
        else:
            async with httpx.AsyncClient(timeout=self.timeout, verify=trust_store()) as store:
                posted = await store.post(
                    form.url,
                    data={field.name: field.value for field in form.fields},
                    files={"file": (started.name, data, started.content_type)},
                )
            if posted.is_error:
                raise ApiError(posted.status_code, "upload_refused", posted.text[:200], None)
        return await self.confirm_file(started.id)

    async def download(self, file_id: UUID) -> bytes:
        """A stored file's bytes: by the signed link, or through the API when
        the store cannot sign one."""
        link = await self.issue_download(file_id)
        if link.url is None:
            return await self.content(file_id)
        async with httpx.AsyncClient(timeout=self.timeout, verify=trust_store()) as store:
            fetched = await store.get(link.url)
        if fetched.is_error:
            raise ApiError(fetched.status_code, "download_refused", fetched.text[:200], None)
        return fetched.content
