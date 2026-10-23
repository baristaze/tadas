"""Files over the live app, on the local store: a task's attachment started,
its parts sent straight to the store by their signed URLs, confirmed,
listed, downloaded straight from the store, and removed; an upload cut off
that resumes; the bounds; the usage; the tenant boundary; and the namespaces
setting that mounts the media routes alone."""

from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import (
    add_member,
    build_container,
    seed_request,
    send_parts,
    send_upload,
    sign_in_as,
)
from fastapi import FastAPI
from store_support import local_store

from tadas.infra.buckets import PART_BYTES
from tadas.om.context import Role
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer

PDF = b"%PDF-1.7 the report"


async def a_task(client: httpx.AsyncClient, headers: dict[str, str], title: str = "Ship") -> str:
    created = await client.post("/v1/tasks", headers=headers, json={"title": title})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def start(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    task_id: str,
    name: str = "report.pdf",
    content_type: str = "application/pdf",
    size: int = len(PDF),
) -> httpx.Response:
    return await client.post(
        f"/v1/tasks/{task_id}/attachments",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"name": name, "content_type": content_type, "size_bytes": size},
    )


async def attach(
    client: httpx.AsyncClient,
    container: AppContainer,
    headers: dict[str, str],
    task_id: str,
    data: bytes = PDF,
) -> dict:
    """The whole flow a client makes: start on the task, ask for the parts,
    send each straight to the store, ask again until none is missing,
    confirm."""
    started = await start(client, headers, task_id, size=len(data))
    assert started.status_code == 201, started.text
    file_id = started.json()["id"]
    await send_upload(client, container, headers, file_id, data)
    confirmed = await client.post(f"/v1/media/files/{file_id}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


async def test_a_task_attachment_goes_up_is_listed_comes_down_and_is_removed(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    task_id = await a_task(client, owner)
    started = await start(client, owner, task_id)
    assert started.status_code == 201, started.text
    pending = started.json()
    assert (pending["status"], pending["purpose"], pending["subject_id"]) == (
        "pending",
        "task_attachment",
        task_id,
    )
    assert "key" not in pending, "where the bytes live is never on the wire"
    listed = await client.get(f"/v1/tasks/{task_id}/attachments", headers=owner)
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"items": [], "next_cursor": None}, "a pending file is not listed"
    early = await client.post(f"/v1/media/files/{pending['id']}/confirm", headers=owner)
    assert early.status_code == 422, "no parts, no confirm"
    assert early.json()["error"]["code"] == "upload_refused"

    stored = await attach(client, container, owner, task_id)
    assert (stored["status"], stored["name"], stored["extension"]) == (
        "stored",
        "report.pdf",
        "pdf",
    )
    listed = await client.get(f"/v1/tasks/{task_id}/attachments", headers=owner)
    assert [f["id"] for f in listed.json()["items"]] == [stored["id"]]

    link = await client.get(f"/v1/media/files/{stored['id']}/download", headers=owner)
    assert link.status_code == 200, link.text
    preview = await client.get(
        f"/v1/media/files/{stored['id']}/download", headers=owner, params={"inline": "true"}
    )
    async with local_store(container.infra.get_buckets()) as store:
        content = await store.get(link.json()["url"])
        shown = await store.get(preview.json()["url"])
    assert content.status_code == 200 and content.content == PDF
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["content-disposition"] == "attachment; filename*=UTF-8''report.pdf"
    assert shown.headers["content-disposition"] == "inline"
    assert shown.headers["content-type"] == "application/pdf"

    removed = await client.delete(f"/v1/tasks/{task_id}/attachments/{stored['id']}", headers=owner)
    assert removed.status_code == 200 and removed.json()["deleted_at"] is not None
    assert (await client.get(f"/v1/tasks/{task_id}/attachments", headers=owner)).json()[
        "items"
    ] == []
    gone = await client.get(f"/v1/media/files/{stored['id']}", headers=owner)
    assert gone.status_code == 404
    usage = (await client.get("/v1/media/usage", headers=owner)).json()
    assert usage["total_count"] == 0, "a deleted file stops counting at once"


async def test_an_attachment_cut_off_resumes_sending_only_the_missing_parts(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """A task attachment of two parts: the first reaches the store and the
    upload stops. Asked again, the API signs the second part alone, under
    the same upload; once it is sent, the confirm stores the file, and the
    download's presigned GET answers every byte."""
    data = b"%PDF-1.7 " + bytes(n % 251 for n in range(PART_BYTES + 1000))
    task_id = await a_task(client, owner)
    started = await start(client, owner, task_id, size=len(data))
    assert started.status_code == 201, started.text
    file_id = started.json()["id"]

    first = await client.post(f"/v1/media/files/{file_id}/upload", headers=owner)
    assert first.status_code == 200, first.text
    planned = first.json()
    assert [(p["number"], p["offset"], p["size_bytes"]) for p in planned["parts"]] == [
        (1, 0, PART_BYTES),
        (2, PART_BYTES, len(data) - PART_BYTES),
    ]
    assert all(p["url"].startswith("http://buckets.test/") for p in planned["parts"])
    cut_off = {**planned, "parts": planned["parts"][:1]}
    assert await send_parts(container, cut_off, data) == [1]
    early = await client.post(f"/v1/media/files/{file_id}/confirm", headers=owner)
    assert early.status_code == 422 and early.json()["error"]["code"] == "upload_refused"

    resumed = await client.post(f"/v1/media/files/{file_id}/upload", headers=owner)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["upload_id"] == planned["upload_id"]
    assert [p["number"] for p in resumed.json()["parts"]] == [2], "only the missing part"
    assert await send_parts(container, resumed.json(), data) == [2]
    done = await client.post(f"/v1/media/files/{file_id}/upload", headers=owner)
    assert done.json()["parts"] == [] and done.json()["remaining"] == 0

    confirmed = await client.post(f"/v1/media/files/{file_id}/confirm", headers=owner)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "stored"
    link = await client.get(f"/v1/media/files/{file_id}/download", headers=owner)
    async with local_store(container.infra.get_buckets()) as store:
        fetched = await store.get(link.json()["url"])
    assert fetched.status_code == 200 and fetched.content == data


async def test_a_retried_start_lands_one_file(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    task_id = await a_task(client, owner)
    headers = {**owner, "Idempotency-Key": str(uuid4())}
    body = {"name": "report.pdf", "content_type": "application/pdf", "size_bytes": 10}
    first = await client.post(f"/v1/tasks/{task_id}/attachments", headers=headers, json=body)
    again = await client.post(f"/v1/tasks/{task_id}/attachments", headers=headers, json=body)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert again.headers["idempotent-replayed"] == "true"
    usage = (await client.get("/v1/media/usage", headers=owner)).json()
    assert usage["pending_size_bytes"] == 10, "one pending file, not two"


@pytest.mark.parametrize(
    ("name", "content_type", "size"),
    [
        ("page.html", "text/html", 10),
        ("image.svg", "image/svg+xml", 10),
        ("report.png", "application/pdf", 10),
        ("report.pdf", "application/pdf", 100 * 1024 * 1024 + 1),
        ("a/b.pdf", "application/pdf", 10),
        ("report.pdf", "application/pdf", 0),
    ],
)
async def test_an_upload_outside_the_bounds_never_starts(
    client: httpx.AsyncClient, owner: dict[str, str], name: str, content_type: str, size: int
) -> None:
    task_id = await a_task(client, owner)
    refused = await start(client, owner, task_id, name, content_type, size)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "validation_failed"


async def test_no_route_takes_or_serves_a_files_bytes(
    app: FastAPI, client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """No route of the app carries a file's bytes, and the issued parts are
    the store's URLs, each signed for its own length."""
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            body = operation.get("requestBody", {}).get("content", {})
            assert set(body) <= {"application/json"}, f"{method} {path} takes {set(body)}"
            for answer in operation.get("responses", {}).values():
                kinds = set(answer.get("content", {}))
                assert kinds <= {"application/json"}, f"{method} {path} serves {kinds}"
    task_id = await a_task(client, owner)
    started = (await start(client, owner, task_id, size=len(PDF))).json()
    issued = await client.post(f"/v1/media/files/{started['id']}/upload", headers=owner)
    (part,) = issued.json()["parts"]
    assert part["url"].startswith("http://buckets.test/")
    assert (part["number"], part["offset"], part["size_bytes"]) == (1, 0, len(PDF))
    for method in ("PUT", "GET"):
        bytes_in = await client.request(
            method, f"/v1/media/files/{started['id']}/content", headers=owner, content=PDF
        )
        assert bytes_in.status_code in (404, 405), f"{method}: {bytes_in.status_code}"
    async with local_store(container.infra.get_buckets()) as store:
        longer = await store.put(part["url"], content=PDF + b"more")
    assert longer.status_code == 403, "the store refuses a part past its length"
    assert await send_parts(container, issued.json(), PDF) == [1]
    confirmed = await client.post(f"/v1/media/files/{started['id']}/confirm", headers=owner)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "stored"


async def test_usage_is_counted_from_the_rows(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    task_id = await a_task(client, owner)
    await attach(client, container, owner, task_id)
    await attach(client, container, owner, task_id, b"12345")
    await start(client, owner, task_id, size=700)
    usage = await client.get("/v1/media/usage", headers=owner)
    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert (body["total_count"], body["total_size_bytes"], body["pending_size_bytes"]) == (
        2,
        len(PDF) + 5,
        700,
    )
    by = {p["purpose"]: p for p in body["purposes"]}
    assert set(by) == {"task_attachment", "voice_dictation", "task_import"}
    assert by["voice_dictation"]["count"] == 0


async def test_deleting_a_task_removes_its_attachments_from_the_usage(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    task_id = await a_task(client, owner)
    await attach(client, container, owner, task_id)
    deleted = await client.delete(f"/v1/tasks/{task_id}", headers={**owner, "If-Match": '"1"'})
    assert deleted.status_code == 200, deleted.text
    usage = (await client.get("/v1/media/usage", headers=owner)).json()
    assert usage["total_count"] == 0
    assert (await client.get(f"/v1/tasks/{task_id}/attachments", headers=owner)).status_code == 404


async def test_a_viewer_reads_attachments_and_starts_none(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    task_id = await a_task(client, owner)
    stored = await attach(client, container, owner, task_id)
    org_id = UUID((await client.get("/v1/me", headers=owner)).json()["org"]["id"])
    await add_member(container, org_id, "vic@example.test", Role.VIEWER)
    viewer = await sign_in_as(client, container, "vic@example.test", org_id)
    listed = await client.get(f"/v1/tasks/{task_id}/attachments", headers=viewer)
    assert [f["id"] for f in listed.json()["items"]] == [stored["id"]]
    assert (await start(client, viewer, task_id)).status_code == 403
    removal = await client.delete(f"/v1/tasks/{task_id}/attachments/{stored['id']}", headers=viewer)
    assert removal.status_code == 403
    kept = await client.get(f"/v1/media/files/{stored['id']}", headers=owner)
    assert kept.status_code == 200 and kept.json()["deleted_at"] is None


async def test_an_upload_is_its_starters_until_it_is_stored(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """Another member reads a pending file but gets no part of it signed, and
    confirms it for nobody."""
    task_id = await a_task(client, owner)
    started = (await start(client, owner, task_id)).json()
    org_id = UUID((await client.get("/v1/me", headers=owner)).json()["org"]["id"])
    await add_member(container, org_id, "mia@example.test", Role.MEMBER)
    mia = await sign_in_as(client, container, "mia@example.test", org_id)
    file_id = started["id"]
    assert (await client.get(f"/v1/media/files/{file_id}", headers=mia)).status_code == 200
    moves: list[tuple[str, str, dict]] = [
        ("POST", f"/v1/media/files/{file_id}/upload", {}),
        ("POST", f"/v1/media/files/{file_id}/confirm", {}),
    ]
    for method, path, extra in moves:
        refused = await client.request(method, path, headers=mia, **extra)
        assert refused.status_code == 403, f"{method} {path}: {refused.status_code}"


async def test_another_tenants_file_answers_as_a_missing_one(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """Tenant B names A's task and A's file on every route that takes one; each
    answer is the 404 an unknown id gets, and A's file is as it was."""
    task_id = await a_task(client, owner)
    stored = await attach(client, container, owner, task_id)
    _, other = await container.managers.tenancy.bootstrap(
        seed_request(), "Other", "other", "eve@other.test", "Eve"
    )
    eve = await sign_in_as(client, container, "eve@other.test", other.id)
    own_task = await a_task(client, eve, "Eve's")
    file_id = stored["id"]
    swept: list[tuple[str, str, dict]] = [
        ("GET", f"/v1/media/files/{file_id}", {}),
        ("POST", f"/v1/media/files/{file_id}/upload", {}),
        ("POST", f"/v1/media/files/{file_id}/confirm", {}),
        ("GET", f"/v1/media/files/{file_id}/download", {}),
        ("GET", f"/v1/tasks/{task_id}/attachments", {}),
        ("DELETE", f"/v1/tasks/{task_id}/attachments/{file_id}", {}),
        ("DELETE", f"/v1/tasks/{own_task}/attachments/{file_id}", {}),
    ]
    for method, path, extra in swept:
        answered = await client.request(method, path, headers=eve, **extra)
        assert answered.status_code == 404, f"{method} {path}: {answered.status_code}"
    assert (await start(client, eve, task_id)).status_code == 404
    assert (await client.get("/v1/media/usage", headers=eve)).json()["total_count"] == 0
    mine = await client.get(f"/v1/media/files/{file_id}", headers=owner)
    assert mine.status_code == 200 and mine.json() == stored


async def test_the_namespaces_setting_mounts_the_media_routes_alone(tmp_path: Path) -> None:
    app = create_app(build_container(tmp_path, namespaces=["media"]))
    paths = set(app.openapi()["paths"])
    assert "/v1/media/usage" in paths
    assert not any(
        p.startswith(("/v1/tasks", "/v1/auth", "/v1/change-events", "/v1/admin")) for p in paths
    )
    whole = set(create_app(build_container(tmp_path)).openapi()["paths"])
    assert paths < whole


def test_a_namespace_the_image_does_not_host_refuses_the_boot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="payroll"):
        create_app(build_container(tmp_path, namespaces=["media", "payroll"]))
