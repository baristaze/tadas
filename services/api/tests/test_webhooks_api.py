"""The identity provider's webhook over the in-process app: the route takes
the body byte for byte and the signature header, checks one against the
other before anything is queued, and queues the delivery for the worker. It
takes no credential and no rate limit; the signature is its check."""

import json
from datetime import timedelta
from functools import partial
from pathlib import Path
from uuid import UUID, uuid5

import httpx
import pytest
from api_support import SMALL_BUDGET, TOTP_KEY, build_container, client_over

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.queues import Queues
from tadas.integrations.identity.deliveries import DELIVERY_NAMESPACE, SIGNATURE_HEADER, sign
from tadas.integrations.identity.twin import TWIN_WEBHOOK_SECRET, IdentityProviderTwinImpl
from tadas.integrations.identity.workos import IdentityProviderWorkOSImpl
from tadas.integrations.impl import configured
from tadas.integrations.impl.configured import IntegrationsConfiguredImpl, IntegrationsOverImpl
from tadas.om.base import utcnow
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.services.api.container import AppContainer
from tadas.services.api.settings import ApiSettings

ROUTE = "/webhooks/identity"
ORG = UUID("01a0eba7-0000-7000-8000-000000000001")


@pytest.fixture
def twin() -> IdentityProviderTwinImpl:
    return IdentityProviderTwinImpl()


@pytest.fixture
def container(tmp_path: Path, twin: IdentityProviderTwinImpl) -> AppContainer:
    return build_container(tmp_path, integrations=IntegrationsOverImpl(twin))


async def queued(container: AppContainer) -> list[bytes]:
    """Every body on the webhooks queue, taken off it."""
    queues = container.infra.get_queues()
    messages = await queues.receive(Queues.WEBHOOKS, 10, timedelta(0), timedelta(seconds=30))
    for message in messages:
        await queues.delete(Queues.WEBHOOKS, message.receipt)
    return [message.body for message in messages]


async def test_a_signed_delivery_is_queued_once_with_its_event(
    client: httpx.AsyncClient, container: AppContainer, twin: IdentityProviderTwinImpl
) -> None:
    body, signature = twin.signed_event(
        "organization.updated",
        {"object": "organization", "id": "org_01", "external_id": str(ORG)},
        event_id="event_01",
    )
    answered = await client.post(ROUTE, content=body, headers={SIGNATURE_HEADER: signature})
    assert answered.status_code == 200, answered.text
    assert answered.json() == {"received": True}

    [sent] = await queued(container)
    message = json.loads(sent.decode("utf-8"))
    key = str(uuid5(DELIVERY_NAMESPACE, "event_01"))
    assert message == {
        "idempotency_key": key,
        "provider": "identity",
        "delivery": twin.verify_delivery(body, signature).model_dump(mode="json"),
    }
    delivery = message["delivery"]
    assert (delivery["key"], delivery["event_id"], delivery["event_type"]) == (
        key,
        "event_01",
        "organization.updated",
    )
    assert (delivery["organization_id"], delivery["organization_external_id"]) == (
        "org_01",
        str(ORG),
    )


async def test_a_bad_or_missing_signature_is_refused_and_queues_nothing(
    client: httpx.AsyncClient, container: AppContainer, twin: IdentityProviderTwinImpl
) -> None:
    """No header, a header signed with another secret, a header no signer
    writes (a byte past ASCII in the signature, a timestamp no clock reads),
    and the right header over a body that is not byte for byte the one
    signed: each is 400 and nothing reaches the queue."""
    body, signature = twin.signed_event("user.created", {"id": "user_01"})
    reserialized = json.dumps(json.loads(body), indent=1).encode()
    stamp = signature.partition(",")[0].encode()
    cases: tuple[tuple[bytes, dict[str, str] | dict[bytes, bytes]], ...] = (
        (body, {}),
        (body, {SIGNATURE_HEADER: sign(body, "whsec_not_ours")}),
        (body, {SIGNATURE_HEADER: "not a signature"}),
        (body, {SIGNATURE_HEADER.encode(): stamp + b", v1=" + b"\xe9" * 64}),
        (body, {SIGNATURE_HEADER: sign(body, "whsec_not_ours", int("9" * 400))}),
        (reserialized, {SIGNATURE_HEADER: signature}),
    )
    for content, headers in cases:
        refused = await client.post(ROUTE, content=content, headers=headers)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["code"] == "webhook_signature_invalid"
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)


async def test_the_route_takes_no_credential_and_no_rate_limit(
    tmp_path: Path, twin: IdentityProviderTwinImpl
) -> None:
    """Past every budget the gateway keeps, from one address with no bearer,
    every signed delivery is queued."""
    container = build_container(
        tmp_path,
        integrations=IntegrationsOverImpl(twin),
        login_rate_limit=SMALL_BUDGET,
        credential_rate_limit_writes=SMALL_BUDGET,
        failed_authentication_limit=SMALL_BUDGET,
    )
    async with client_over(container) as client:
        for index in range(SMALL_BUDGET * 2):
            body, signature = twin.signed_event("user.updated", {"id": f"user_{index}"})
            answered = await client.post(ROUTE, content=body, headers={SIGNATURE_HEADER: signature})
            assert answered.status_code == 200, (index, answered.text)
        assert len(await queued(container)) == SMALL_BUDGET * 2


async def workos_answers_invalid_grant(request: httpx.Request) -> httpx.Response:
    """WorkOS as the start's credential check meets it for the application's
    own key; the webhook makes no call."""
    return httpx.Response(400, json={"error": "invalid_grant"})


@pytest.mark.parametrize("provider", ["none", "workos without a secret"])
async def test_a_process_with_no_secret_answers_503(tmp_path: Path, provider: str) -> None:
    """A process that holds no signing secret cannot check a delivery, so it
    refuses every one as unavailable, the answer the provider retries."""
    if provider == "none":
        container = build_container(tmp_path)
    else:
        workos = IdentityProviderWorkOSImpl(
            client_id="client_test",
            api_key="sk_test_not_a_key",
            timeout=timedelta(seconds=10),
            transport=httpx.MockTransport(workos_answers_invalid_grant),
            webhook_secret=None,
        )
        container = build_container(tmp_path, integrations=IntegrationsOverImpl(workos))
    body, signature = IdentityProviderTwinImpl().signed_event("user.created", {"id": "user_01"})
    async with client_over(container) as client:
        refused = await client.post(ROUTE, content=body, headers={SIGNATURE_HEADER: signature})
    assert refused.status_code == 503, refused.text
    assert refused.json()["error"]["code"] == "unavailable"
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)


async def test_a_replayed_delivery_is_queued_again_under_the_same_key(
    client: httpx.AsyncClient, container: AppContainer, twin: IdentityProviderTwinImpl
) -> None:
    """The provider sends an event again, byte for byte and inside the
    window, when it did not hear the answer. The route takes the copy, and
    the key it queues it under is the first's, so the worker applies it once."""
    body, signature = twin.signed_event(
        "organization.updated",
        {"object": "organization", "id": "org_01", "external_id": str(ORG)},
        event_id="event_02",
    )
    for _ in range(2):
        answered = await client.post(ROUTE, content=body, headers={SIGNATURE_HEADER: signature})
        assert answered.status_code == 200, answered.text
    first, second = (json.loads(sent) for sent in await queued(container))
    assert first == second
    assert first["idempotency_key"] == str(uuid5(DELIVERY_NAMESPACE, "event_02"))


async def test_a_signature_outside_the_window_is_refused_and_queues_nothing(
    client: httpx.AsyncClient, container: AppContainer, twin: IdentityProviderTwinImpl
) -> None:
    """A delivery signed by the twin's own secret four minutes ago, past the
    three the check allows, is a replay the route never takes."""
    body, _ = twin.signed_event("user.updated", {"id": "user_01"})
    stale = int((utcnow() - timedelta(minutes=4)).timestamp() * 1000)
    refused = await client.post(
        ROUTE, content=body, headers={SIGNATURE_HEADER: sign(body, TWIN_WEBHOOK_SECRET, stale)}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "webhook_signature_invalid"
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)


async def test_a_secret_left_off_starts_the_api_and_refuses_every_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployed environment holds the endpoint's secret as "off" until the
    endpoint is made. Read from the process environment as the API reads it,
    "off" is no secret: the API starts on WorkOS with its key, and every
    identity delivery, the twin's signed one included, answers 503 with
    nothing queued, the answer the provider retries."""
    monkeypatch.setenv("TADAS_WORKOS_WEBHOOK_SECRET", "off")
    settings = ApiSettings.model_validate(
        {
            "_env_file": None,
            "environment": "staging",
            "identity_provider": "workos",
            "workos_client_id": "client_test",
            "workos_api_key": "sk_test_not_a_key",
            "sign_in_redirect_uris": ["https://app.staging.tadas.example/auth/callback"],
            "sign_out_return_uris": ["https://app.staging.tadas.example/signed-out"],
            "totp_encryption_key": TOTP_KEY,
        }
    )
    assert settings.workos_webhook_secret is None
    monkeypatch.setattr(
        configured,
        "IdentityProviderWorkOSImpl",
        partial(
            IdentityProviderWorkOSImpl,
            transport=httpx.MockTransport(workos_answers_invalid_grant),
        ),
    )
    container = AppContainer.over(
        settings,
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        IntegrationsConfiguredImpl(settings, settings.environment, deployed=True),
    )
    assert isinstance(container.integrations.get_identity_provider(), IdentityProviderWorkOSImpl)
    twin = IdentityProviderTwinImpl()
    async with client_over(container) as client:
        assert (await client.get("/healthz")).status_code == 200
        for event_type in ("organization.updated", "user.deleted"):
            body, signature = twin.signed_event(event_type, {"id": "org_01"})
            refused = await client.post(ROUTE, content=body, headers={SIGNATURE_HEADER: signature})
            assert refused.status_code == 503, refused.text
            assert refused.json()["error"]["code"] == "unavailable"
    depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
    assert (depth.visible, depth.in_flight) == (0, 0)
