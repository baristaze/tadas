"""The Sentry-shaped read both impls share: GlitchTip locally and Sentry in
the cloud answer the same issue and event routes, under a token. An error
event is found by the `request_id` tag the platform puts on every event."""

from typing import Any

import httpx

from tadas.ops.signals import ErrorEventFound

RECENT_ISSUES = 25


async def find_error_event(
    http: httpx.AsyncClient, base_url: str, token: str, org: str, request_id: str
) -> ErrorEventFound | None:
    """The issues the search names for the id, then the recent ones, and in
    each the event whose `request_id` tag is the id. The search is a
    convenience; the tag is the proof."""
    headers = {"Authorization": f"Bearer {token}"}
    base = base_url.rstrip("/")
    seen: set[str] = set()
    for params in (
        {"query": request_id, "limit": RECENT_ISSUES},
        {"limit": RECENT_ISSUES, "sort": "-last_seen"},
    ):
        response = await http.get(
            f"{base}/api/0/organizations/{org}/issues/", params=params, headers=headers
        )
        response.raise_for_status()
        for issue in response.json():
            issue_id = str(issue["id"])
            if issue_id in seen:
                continue
            seen.add(issue_id)
            events = await http.get(f"{base}/api/0/issues/{issue_id}/events/", headers=headers)
            events.raise_for_status()
            for event in events.json():
                if tag_value(event, "request_id") == request_id:
                    return ErrorEventFound(
                        event_id=str(event.get("eventID") or event.get("id")),
                        issue_id=issue_id,
                        title=str(issue.get("title", "")),
                    )
    return None


def tag_value(event: dict[str, Any], key: str) -> str | None:
    tags = event.get("tags") or []
    if isinstance(tags, dict):
        value = tags.get(key)
        return None if value is None else str(value)
    for tag in tags:
        if isinstance(tag, dict) and tag.get("key") == key:
            return None if tag.get("value") is None else str(tag["value"])
    return None
