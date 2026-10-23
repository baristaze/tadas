"""The tasks namespace's calls: an org's tasks, their attachments, a CSV
import, and an org's tasks on the operator plane, whose bearer is an operator
token. An attachment and an import file are media files, so these calls build
on the media namespace's upload."""

import asyncio
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from tadas.client.calls.media import MediaCalls
from tadas.client.transport import LIMIT_MAX, UNSET, Unset
from tadas.client.types.media import FilePageView, FileView
from tadas.client.types.tasks import (
    BulkAction,
    BulkTasksView,
    ImportPageView,
    ImportView,
    TaskCountView,
    TaskPageView,
    TaskScope,
    TaskStatus,
    TaskView,
)


class TasksCalls(MediaCalls):
    """Tasks, their attachments, imports, and an org's tasks for an operator."""

    async def tasks(
        self,
        status: TaskStatus = TaskStatus.open,
        scope: TaskScope = TaskScope.team,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> TaskPageView:
        params: dict[str, Any] = {"status": status.value, "scope": scope.value, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return TaskPageView.model_validate(await self.request("GET", "/v1/tasks", params=params))

    async def count_tasks(
        self, status: TaskStatus = TaskStatus.open, scope: TaskScope = TaskScope.team
    ) -> TaskCountView:
        """How many tasks one list shows, the done one without the archive."""
        params = {"status": status.value, "scope": scope.value}
        return TaskCountView.model_validate(
            await self.request("GET", "/v1/tasks/count", params=params)
        )

    async def change_tasks(
        self,
        action: BulkAction,
        *,
        ids: Sequence[UUID] | None = None,
        scope: TaskScope | None = None,
        status: TaskStatus | None = None,
        idempotency_key: str | None = None,
    ) -> BulkTasksView:
        """Completes or reopens many tasks in one call: the ones named in `ids`,
        or with `scope` and `status` every task of that list, as the server
        reads it. Always under an idempotency key, so a retry answers what the
        first call did. The answer names what changed, which the other action
        over those ids undoes."""
        body: dict[str, Any] = {"action": action.value}
        if ids is not None:
            body["ids"] = [str(task_id) for task_id in ids]
        if scope is not None or status is not None:
            body["all"] = {
                "scope": (scope or TaskScope.team).value,
                "status": (status or TaskStatus.open).value,
            }
        changed = await self.request(
            "POST", "/v1/tasks/bulk", json=body, idempotency_key=idempotency_key or str(uuid4())
        )
        return BulkTasksView.model_validate(changed)

    async def task(self, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self.request("GET", f"/v1/tasks/{task_id}"))

    async def create_task(
        self,
        title: str,
        *,
        notes: str = "",
        assignee_id: UUID | None = None,
        due_on: date | None = None,
        idempotency_key: str | None = None,
    ) -> TaskView:
        """A creating call always carries an idempotency key; a retry with the
        same key returns the task the first call created. `due_on` is a date,
        never a time: the reminder goes out at nine in the morning of it, in
        the time zone of the person the task is for."""
        body: dict[str, Any] = {"title": title, "notes": notes}
        if assignee_id is not None:
            body["assignee_id"] = str(assignee_id)
        if due_on is not None:
            body["due_on"] = due_on.isoformat()
        created = await self.request(
            "POST", "/v1/tasks", json=body, idempotency_key=idempotency_key or str(uuid4())
        )
        return TaskView.model_validate(created)

    async def update_task(
        self,
        task_id: UUID,
        *,
        version: int,
        title: str | None = None,
        notes: str | None = None,
        status: TaskStatus | None = None,
        assignee_id: UUID | Unset | None = UNSET,
        due_on: date | Unset | None = UNSET,
    ) -> TaskView:
        """A partial update: only what the caller passes is sent. `assignee_id=None`
        unassigns; leaving it out keeps the assignee. `due_on` is the same:
        None clears the due date, and leaving it out keeps it. `version` is the task's as
        the caller read it, sent in `If-Match`; the API refuses the update with
        412 `precondition_failed` when the task changed since, and the caller
        reads again."""
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if status is not None:
            body["status"] = status.value
        if not isinstance(assignee_id, Unset):
            body["assignee_id"] = None if assignee_id is None else str(assignee_id)
        if not isinstance(due_on, Unset):
            body["due_on"] = None if due_on is None else due_on.isoformat()
        return TaskView.model_validate(
            await self.request("PATCH", f"/v1/tasks/{task_id}", json=body, if_match=version)
        )

    async def move_task(self, task_id: UUID, after_id: UUID | None, version: int) -> TaskView:
        """`version` is the moved task's, as on `update_task`; a move is a POST,
        so it rides the body as `expected_version`."""
        body = {
            "after_id": None if after_id is None else str(after_id),
            "expected_version": version,
        }
        return TaskView.model_validate(
            await self.request("POST", f"/v1/tasks/{task_id}/move", json=body)
        )

    async def delete_task(self, task_id: UUID, version: int) -> TaskView:
        """`version` is the task's, as on `update_task`, in `If-Match`."""
        return TaskView.model_validate(
            await self.request("DELETE", f"/v1/tasks/{task_id}", if_match=version)
        )

    # A task's attachments: media files the task holds

    async def attachments(
        self, task_id: UUID, *, cursor: str | None = None, limit: int = LIMIT_MAX
    ) -> FilePageView:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        page = await self.request("GET", f"/v1/tasks/{task_id}/attachments", params=params)
        return FilePageView.model_validate(page)

    async def every_attachment(self, task_id: UUID, limit: int = LIMIT_MAX) -> list[FileView]:
        """A task's stored attachments, oldest first, following the cursor to the end."""
        files: list[FileView] = []
        cursor: str | None = None
        while True:
            page = await self.attachments(task_id, cursor=cursor, limit=limit)
            files.extend(page.items)
            if page.next_cursor is None:
                return files
            cursor = page.next_cursor

    async def start_attachment(
        self,
        task_id: UUID,
        name: str,
        content_type: str,
        size_bytes: int,
        *,
        idempotency_key: str | None = None,
    ) -> FileView:
        """A pending attachment: the upload may begin. Always under an
        idempotency key, so a retry lands one file."""
        body = {"name": name, "content_type": content_type, "size_bytes": size_bytes}
        started = await self.request(
            "POST",
            f"/v1/tasks/{task_id}/attachments",
            json=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return FileView.model_validate(started)

    async def remove_attachment(self, task_id: UUID, file_id: UUID) -> FileView:
        removed = await self.request("DELETE", f"/v1/tasks/{task_id}/attachments/{file_id}")
        return FileView.model_validate(removed)

    async def attach(
        self, task_id: UUID, name: str, content_type: str, source: Path | bytes
    ) -> FileView:
        """The whole upload of a task's attachment: start it, then `upload`,
        which sends its parts straight to the store a chunk at a time. An
        upload cut off goes on with `upload` on the file this started."""
        if isinstance(source, bytes):
            size = len(source)
        else:
            size = (await asyncio.to_thread(source.stat)).st_size
        started = await self.start_attachment(task_id, name, content_type, size)
        return await self.upload(started, source)

    # Imports

    async def start_import_file(
        self, name: str, size_bytes: int, *, idempotency_key: str | None = None
    ) -> FileView:
        """A pending CSV file to import: the upload may begin. Always under an
        idempotency key, so a retry lands one file."""
        body = {"name": name, "content_type": "text/csv", "size_bytes": size_bytes}
        started = await self.request(
            "POST",
            "/v1/tasks/imports/files",
            json=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return FileView.model_validate(started)

    async def start_import(
        self, file_id: UUID, *, idempotency_key: str | None = None
    ) -> ImportView:
        """Starts the import of a stored file; the worker reads it."""
        started = await self.request(
            "POST",
            "/v1/tasks/imports",
            json={"file_id": str(file_id)},
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return ImportView.model_validate(started)

    async def import_tasks(self, name: str, data: bytes) -> ImportView:
        """The whole start: the file's upload, then its import."""
        started = await self.start_import_file(name, len(data))
        stored = await self.upload(started, data)
        return await self.start_import(stored.id)

    async def task_import(self, import_id: UUID) -> ImportView:
        return ImportView.model_validate(
            await self.request("GET", f"/v1/tasks/imports/{import_id}")
        )

    async def task_imports(self, limit: int = 10) -> ImportPageView:
        page = await self.request("GET", "/v1/tasks/imports", params={"limit": limit})
        return ImportPageView.model_validate(page)

    async def resume_import(self, import_id: UUID) -> ImportView:
        resumed = await self.request("POST", f"/v1/tasks/imports/{import_id}/resume")
        return ImportView.model_validate(resumed)

    async def cancel_import(self, import_id: UUID, reason: str | None = None) -> ImportView:
        """Ends a running or a parked import; the tasks it made stay. `reason`
        is logged with it."""
        cancelled = await self.request(
            "POST",
            f"/v1/tasks/imports/{import_id}/cancel",
            json=None if reason is None else {"reason": reason},
        )
        return ImportView.model_validate(cancelled)

    # The operator plane

    async def admin_tasks(
        self,
        org_id: UUID,
        status: TaskStatus = TaskStatus.open,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> TaskPageView:
        params: dict[str, Any] = {"status": status.value, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = await self.request("GET", f"/v1/admin/orgs/{org_id}/tasks", params=params)
        return TaskPageView.model_validate(body)
