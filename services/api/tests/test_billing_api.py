"""The billing routes and the processor's webhook over the in-process app and
the payment processor's twin: the plan an org reads, the typed refusal a
lever answers with, a checkout, a signed delivery queued and applied once,
and a cancellation that holds the plan to its period's end."""

import json
from datetime import timedelta
from typing import cast
from uuid import UUID

import httpx
import pytest
from api_support import add_member, on_plan, seed_request, sign_in, sign_in_as

from tadas.infra.queues import Queues
from tadas.integrations.payments import ProviderDelivery
from tadas.integrations.payments.deliveries import sign
from tadas.integrations.payments.twin import PaymentsTwinImpl
from tadas.om.base import EMPTY_UUID
from tadas.om.billing.types.plan import Plan
from tadas.om.opcontext import Role
from tadas.services.api.container import AppContainer

PORTAL = "http://localhost:5173/settings/billing"


def twin_of(container: AppContainer) -> PaymentsTwinImpl:
    return cast(PaymentsTwinImpl, container.payments)


async def org_id_of(client: httpx.AsyncClient, headers: dict[str, str]) -> UUID:
    return UUID((await client.get("/v1/orgs/current", headers=headers)).json()["id"])


async def drain(container: AppContainer) -> list[bool]:
    """What the worker does with every delivery the route queued: find the
    org, mint its service context, apply, delete. Answers each apply."""
    queues = container.infra.get_queues()
    applied: list[bool] = []
    for message in await queues.receive(Queues.WEBHOOKS, 10, timedelta(0), timedelta(30)):
        body = json.loads(message.body)
        delivery = ProviderDelivery.model_validate(body["delivery"])
        assert body["idempotency_key"] == str(delivery.idempotency_key)
        billing = container.managers.billing
        org_id = await billing.org_of_delivery(seed_request(), delivery)
        assert org_id is not None
        ctx = await container.managers.tenancy.service_context(seed_request(), org_id, EMPTY_UUID)
        applied.append(await billing.apply_delivery(ctx, delivery))
        await queues.delete(Queues.WEBHOOKS, message.receipt)
    return applied


async def pay(client: httpx.AsyncClient, container: AppContainer, headers: dict[str, str]) -> None:
    """The owner starts a checkout for Pro, pays, and the delivery arrives."""
    started = await client.post(
        "/v1/billing/checkout", headers=headers, json={"plan": "pro", "return_url": PORTAL}
    )
    assert started.status_code == 201, started.text
    payload, signature = twin_of(container).complete_checkout(started.json()["url"])
    delivered = await client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": signature}
    )
    assert delivered.status_code == 200 and delivered.json() == {"received": True}
    assert await drain(container) == [True]


@pytest.fixture
async def free(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    return await sign_in(client, container, plan=None)


async def test_a_new_org_reads_free_and_the_plans_on_offer(
    client: httpx.AsyncClient, free: dict[str, str]
) -> None:
    billing = await client.get("/v1/billing", headers=free)
    assert billing.status_code == 200, billing.text
    body = billing.json()
    assert (body["plan"], body["paid_plan"], body["seats"], body["active_tasks"]) == (
        "free",
        None,
        1,
        0,
    )
    assert body["limits"] == {
        "members": 1,
        "api_keys": False,
        "active_tasks": 10,
        "storage_bytes": 1024**3,
    }
    assert body["can_manage"] is True and body["monthly_cents"] == 0
    offers = {offer["plan"]: offer for offer in body["plans"]}
    assert list(offers) == ["free", "pro", "team", "max"]
    assert (offers["max"]["flat_cents"], offers["max"]["included_seats"]) == (3000, 10)
    assert offers["max"]["per_seat_cents"] == 300


async def test_the_eleventh_active_task_is_a_typed_refusal_naming_the_plan_that_lifts_it(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    for n in range(10):
        made = await client.post("/v1/tasks", headers=free, json={"title": f"task {n}"})
        assert made.status_code == 201, made.text
    refused = await client.post("/v1/tasks", headers=free, json={"title": "one too many"})
    assert refused.status_code == 402, refused.text
    error = refused.json()["error"]
    assert error["code"] == "plan_limit_reached"
    assert error["message"] == "the free plan allows 10 active tasks"
    assert error["plan_limit"] == {
        "lever": "active_tasks",
        "plan": "free",
        "limit": 10,
        "suggested_plan": "pro",
    }
    assert error["request_id"] == refused.headers["x-request-id"]
    # Paid for, the same task lands.
    await pay(client, container, free)
    landed = await client.post("/v1/tasks", headers=free, json={"title": "one too many"})
    assert landed.status_code == 201, landed.text
    assert (await client.get("/v1/billing", headers=free)).json()["active_tasks"] == 11


async def test_a_refused_create_under_a_key_lands_on_its_retry_after_an_upgrade(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    """A plan's bound is an answer about now: the marker is released, not
    kept, so the retry of the same create lands once the org has room."""
    for n in range(10):
        await client.post("/v1/tasks", headers=free, json={"title": f"task {n}"})
    keyed = {**free, "Idempotency-Key": "the-eleventh"}
    first = await client.post("/v1/tasks", headers=keyed, json={"title": "eleventh"})
    assert first.status_code == 402
    await on_plan(container, await org_id_of(client, free), Plan.PRO)
    retried = await client.post("/v1/tasks", headers=keyed, json={"title": "eleventh"})
    assert retried.status_code == 201, retried.text
    assert "Idempotent-Replayed" not in retried.headers


async def test_the_first_api_key_on_free_is_refused(
    client: httpx.AsyncClient, free: dict[str, str]
) -> None:
    refused = await client.post("/v1/api-keys", headers=free, json={"name": "ci", "role": "member"})
    assert refused.status_code == 402, refused.text
    assert refused.json()["error"]["plan_limit"]["lever"] == "api_keys"
    assert refused.json()["error"]["plan_limit"]["suggested_plan"] == "pro"


async def test_a_checkout_comes_back_to_the_portal_and_nowhere_else(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    started = await client.post(
        "/v1/billing/checkout", headers=free, json={"plan": "max", "return_url": PORTAL}
    )
    assert started.status_code == 201, started.text
    assert started.json()["url"].startswith("https://checkout.twin.invalid/")
    session = next(iter(twin_of(container).sessions.values()))
    assert session["success_url"] == f"{PORTAL}?checkout=done"
    assert session["cancel_url"] == f"{PORTAL}?checkout=cancelled"
    assert session["quantity"] == 1  # the one member
    for elsewhere in ("https://evil.example/billing", "javascript:alert(1)", "/settings"):
        refused = await client.post(
            "/v1/billing/checkout", headers=free, json={"plan": "pro", "return_url": elsewhere}
        )
        assert refused.status_code == 422, refused.text
    free_plan = await client.post(
        "/v1/billing/checkout", headers=free, json={"plan": "free", "return_url": PORTAL}
    )
    assert free_plan.status_code == 422


async def test_a_member_reads_the_plan_and_is_refused_every_change(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    org_id = await org_id_of(client, free)
    await add_member(container, org_id, "bob@example.test", "pw-1234", Role.MEMBER)
    bob = await sign_in_as(client, "bob@example.test", "pw-1234", org_id)
    read = await client.get("/v1/billing", headers=bob)
    assert read.status_code == 200 and read.json()["can_manage"] is False
    assert read.json()["seats"] == 2
    for path, body in (
        ("/v1/billing/checkout", {"plan": "pro", "return_url": PORTAL}),
        ("/v1/billing/portal", {"return_url": PORTAL}),
        ("/v1/billing/cancel", None),
    ):
        refused = await client.post(path, headers=bob, json=body)
        assert refused.status_code == 403, (path, refused.text)


async def test_a_delivery_that_does_not_check_out_is_refused_and_queues_nothing(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    payload = b'{"id": "evt_forged", "type": "invoice.paid", "created": 1}'
    for headers in ({}, {"Stripe-Signature": sign(payload, "whsec_not_ours")}):
        refused = await client.post("/webhooks/stripe", content=payload, headers=headers)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["code"] == "webhook_signature_invalid"
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)


async def test_the_same_delivery_twice_is_queued_twice_and_applied_once(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    await pay(client, container, free)
    twin = twin_of(container)
    subscription = next(iter(twin.subscriptions))
    twin.move(subscription, cancel_at_period_end=True)
    payload, signature = twin.subscription_event("customer.subscription.updated", subscription)
    for _ in range(2):
        delivered = await client.post(
            "/webhooks/stripe", content=payload, headers={"Stripe-Signature": signature}
        )
        assert delivered.status_code == 200
    assert await drain(container) == [True, False]
    billing = (await client.get("/v1/billing", headers=free)).json()
    assert billing["cancel_at_period_end"] is True and billing["ends_at"] is not None


async def test_cancel_holds_the_plan_to_the_period_end_and_resume_takes_it_back(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    nothing = await client.post("/v1/billing/cancel", headers=free)
    assert nothing.status_code == 404
    await pay(client, container, free)
    cancelled = await client.post("/v1/billing/cancel", headers=free)
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert (body["plan"], body["plan_after"], body["cancel_at_period_end"]) == ("pro", "free", True)
    assert body["ends_at"] == body["current_period_end"] and body["monthly_cents"] == 500
    resumed = (await client.post("/v1/billing/resume", headers=free)).json()
    assert (resumed["plan"], resumed["ends_at"], resumed["plan_after"]) == ("pro", None, None)
    portal = await client.post("/v1/billing/portal", headers=free, json={"return_url": PORTAL})
    assert portal.status_code == 200 and portal.json()["url"].startswith("https://billing.twin")


async def test_every_other_org_is_untouched_by_a_delivery(
    client: httpx.AsyncClient, container: AppContainer, free: dict[str, str]
) -> None:
    _, other = await container.managers.tenancy.bootstrap(
        seed_request(), "Other", "other", "otto@example.test", "pw-1234", "Otto"
    )
    await pay(client, container, free)
    otto = await sign_in_as(client, "otto@example.test", "pw-1234", other.id)
    assert (await client.get("/v1/billing", headers=otto)).json()["plan"] == "free"
