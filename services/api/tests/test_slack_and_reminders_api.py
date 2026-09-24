"""The wire of reminders: a due time set, moved, and cleared on a task, and
refused without its offset. Slack's own wire is `test_slack_api.py`."""

from datetime import UTC, datetime, timedelta

import httpx


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
