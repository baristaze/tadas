"""The wire of reminders and Slack: a due time set, moved, and cleared on a
task, and refused without its offset; the org's Slack connection read by any
member and changed by an owner or an admin alone; a link code shown once."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from api_support import add_member, sign_in_as

from tadas.om.opcontext import Role
from tadas.services.api.container import AppContainer


async def test_a_due_time_is_set_moved_and_cleared(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    due = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    created = await client.post(
        "/v1/tasks", headers=owner, json={"title": "Call the bank", "remind_at": due.isoformat()}
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert datetime.fromisoformat(task["remind_at"]) == due and task["reminded_at"] is None

    later = due + timedelta(hours=2)
    moved = await client.patch(
        f"/v1/tasks/{task['id']}",
        headers={**owner, "If-Match": f'"{task["version"]}"'},
        json={"remind_at": later.isoformat()},
    )
    assert moved.status_code == 200, moved.text
    assert datetime.fromisoformat(moved.json()["remind_at"]) == later

    renamed = await client.patch(
        f"/v1/tasks/{task['id']}",
        headers={**owner, "If-Match": f'"{moved.json()["version"]}"'},
        json={"title": "Call the bank today"},
    )
    assert datetime.fromisoformat(renamed.json()["remind_at"]) == later, "absent keeps it"

    cleared = await client.patch(
        f"/v1/tasks/{task['id']}",
        headers={**owner, "If-Match": f'"{renamed.json()["version"]}"'},
        json={"remind_at": None},
    )
    assert cleared.status_code == 200 and cleared.json()["remind_at"] is None


async def test_a_due_time_without_its_offset_is_refused(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    naive = client.post(
        "/v1/tasks", headers=owner, json={"title": "When?", "remind_at": "2026-10-01T09:00:00"}
    )
    assert (await naive).status_code == 422


async def test_an_owner_connects_and_disconnects_and_a_member_reads(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    status = await client.get("/v1/slack/connection", headers=owner)
    assert status.status_code == 200 and status.json() == {"connection": None}

    issued = await client.post("/v1/slack/link-codes", headers=owner)
    assert issued.status_code == 201, issued.text
    code = issued.json()["code"]
    assert len(code) == 9 and code[4] == "-"
    assert datetime.fromisoformat(issued.json()["expires_at"]) > datetime.now(UTC)

    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    await add_member(container, org_id, "bob@example.test", Role.MEMBER)
    bob = await sign_in_as(client, "bob@example.test", org_id)
    assert (await client.get("/v1/slack/connection", headers=bob)).status_code == 200
    refused = await client.post("/v1/slack/link-codes", headers=bob)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "not_authorized"
    assert (await client.delete("/v1/slack/connection", headers=bob)).status_code == 403

    gone = await client.delete("/v1/slack/connection", headers=owner)
    assert gone.status_code == 200 and gone.json() == {"connection": None}
