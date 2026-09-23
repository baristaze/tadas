"""The WorkOS client over a fake transport: the requests it sends, and every
answer translated into the integration's own shapes and exceptions."""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from tadas.integrations.exceptions import (
    DeviceDenied,
    DeviceExpired,
    DevicePending,
    DeviceSlowDown,
    ProviderConflict,
    ProviderRefused,
    ProviderUnavailable,
)
from tadas.integrations.identity import InvitationState
from tadas.integrations.identity.workos import IdentityProviderWorkOSImpl

CLIENT_ID = "client_test"
API_KEY = "sk_test_secret_value"
NOW = "2026-09-22T10:00:00.000Z"

USER = {
    "object": "user",
    "id": "user_1",
    "email": "dee@example.test",
    "email_verified": True,
    "first_name": "Dee",
    "last_name": "Doe",
    "profile_picture_url": None,
    "external_id": None,
    "last_sign_in_at": None,
    "created_at": NOW,
    "updated_at": NOW,
}


def organization(org_id: str, external_id: str | None, domains: list[tuple[str, str]]) -> Any:
    return {
        "object": "organization",
        "id": org_id,
        "name": "Acme",
        "external_id": external_id,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
        "domains": [
            {
                "object": "organization_domain",
                "id": f"org_domain_{n}",
                "organization_id": org_id,
                "domain": domain,
                "state": state,
                "created_at": NOW,
                "updated_at": NOW,
            }
            for n, (domain, state) in enumerate(domains)
        ],
    }


def invitation(invitation_id: str, state: str, accepted_user_id: str | None = None) -> Any:
    return {
        "object": "invitation",
        "id": invitation_id,
        "email": "bob@acme.example",
        "state": state,
        "accepted_at": None,
        "revoked_at": None,
        "expires_at": "2026-09-29T10:00:00.000Z",
        "organization_id": "org_1",
        "inviter_user_id": None,
        "accepted_user_id": accepted_user_id,
        "role_slug": None,
        "created_at": NOW,
        "updated_at": NOW,
        "token": "tok",
        "accept_invitation_url": "https://auth.example/invite?token=tok",
    }


class Recorder:
    def __init__(self, answer: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._answer = answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._answer(request)


def provider(answer: Callable[[httpx.Request], httpx.Response]) -> tuple[Any, Recorder]:
    recorder = Recorder(answer)
    made = IdentityProviderWorkOSImpl(
        client_id=CLIENT_ID,
        api_key=API_KEY,
        timeout=timedelta(seconds=5),
        # One attempt per call: the SDK's own retries are its business.
        max_retries=0,
        transport=httpx.MockTransport(recorder),
    )
    return made, recorder


def body_of(request: httpx.Request) -> Any:
    return json.loads(request.content or b"{}")


def test_the_authorization_url_names_the_application_the_redirect_and_the_state() -> None:
    made, recorder = provider(lambda r: httpx.Response(500))
    url = made.authorization_url(
        redirect_uri="http://localhost:55173/auth/callback",
        state="abc",
        code_challenge="the-challenge",
        invitation_token="inv",
        screen_hint="sign-up",
    )
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "api.workos.com",
        "/user_management/authorize",
    )
    assert query == {
        "client_id": CLIENT_ID,
        "redirect_uri": "http://localhost:55173/auth/callback",
        "state": "abc",
        "code_challenge": "the-challenge",
        "code_challenge_method": "S256",
        "provider": "authkit",
        "response_type": "code",
        "invitation_token": "inv",
        "screen_hint": "sign-up",
    }
    assert API_KEY not in url and recorder.requests == []
    assert made.issuer == f"https://api.workos.com/user_management/{CLIENT_ID}"


async def test_a_code_is_exchanged_with_its_verifier_and_no_secret() -> None:
    made, recorder = provider(
        lambda r: httpx.Response(
            200,
            json={
                "user": USER,
                "access_token": "at",
                "refresh_token": "rt",
                "organization_id": "org_1",
                "authentication_method": "SSO",
            },
        )
    )
    signed_in = await made.authenticate_code(
        "the-code", code_verifier="the-verifier", invitation_token="inv"
    )
    assert signed_in.user.id == "user_1" and signed_in.user.email_verified
    assert signed_in.user.display_name == "Dee Doe"
    assert signed_in.organization_id == "org_1" and signed_in.via_sso
    [sent] = recorder.requests
    assert sent.url.path == "/user_management/authenticate"
    body = body_of(sent)
    assert body["grant_type"] == "authorization_code" and body["code"] == "the-code"
    # The application's public client: the verifier goes, and no secret,
    # since an AuthKit application's secret is not the environment's key.
    assert body["client_id"] == CLIENT_ID and "client_secret" not in body
    assert body["code_verifier"] == "the-verifier" and body["invitation_token"] == "inv"
    assert API_KEY not in sent.headers.get("authorization", "")


async def test_a_sign_in_by_another_method_is_not_a_single_sign_on() -> None:
    made, _ = provider(
        lambda r: httpx.Response(
            200,
            json={
                "user": USER,
                "access_token": "at",
                "refresh_token": "rt",
                "authentication_method": "GoogleOAuth",
            },
        )
    )
    signed_in = await made.authenticate_code("c", code_verifier="v")
    assert not signed_in.via_sso and signed_in.organization_id is None


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        ("authorization_pending", DevicePending),
        ("slow_down", DeviceSlowDown),
        ("access_denied", DeviceDenied),
        ("expired_token", DeviceExpired),
        ("invalid_grant", ProviderRefused),
    ],
)
async def test_the_device_answers_map_to_the_integrations_own(
    error: str, raised: type[Exception]
) -> None:
    made, recorder = provider(
        lambda r: httpx.Response(400, json={"error": error, "error_description": error})
    )
    with pytest.raises(raised):
        await made.authenticate_device("dev-code")
    body = body_of(recorder.requests[0])
    assert body["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
    assert body["device_code"] == "dev-code"


async def test_a_device_sign_in_starts_for_the_application() -> None:
    made, recorder = provider(
        lambda r: httpx.Response(
            200,
            json={
                "device_code": "dc",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://auth.example/device",
                "verification_uri_complete": "https://auth.example/device?user_code=ABCD-EFGH",
                "expires_in": 300,
                "interval": 5,
            },
        )
    )
    started = await made.start_device()
    assert (started.user_code, started.expires_in, started.interval) == ("ABCD-EFGH", 300, 5)
    assert body_of(recorder.requests[0])["client_id"] == CLIENT_ID


@pytest.mark.parametrize("status", [500, 503])
async def test_a_server_error_is_unavailable_and_never_names_the_key(status: int) -> None:
    made, _ = provider(lambda r: httpx.Response(status, json={"message": "down"}))
    with pytest.raises(ProviderUnavailable) as raised:
        await made.authenticate_code("c", code_verifier="v")
    assert API_KEY not in str(raised.value)


async def test_a_network_failure_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    made, _ = provider(refuse)
    with pytest.raises(ProviderUnavailable):
        await made.start_device()


async def test_an_unprocessable_invitation_is_a_conflict() -> None:
    made, _ = provider(
        lambda r: httpx.Response(422, json={"message": "already invited", "code": "invite_exists"})
    )
    with pytest.raises(ProviderConflict) as raised:
        await made.send_invitation(
            email="bob@acme.example", organization_id="org_1", expires_in_days=7
        )
    assert API_KEY not in str(raised.value)


async def test_an_organization_is_found_by_its_external_id_else_created() -> None:
    def found(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/organizations/external_id/tadas-org"
        return httpx.Response(
            200,
            json=organization(
                "org_1", "tadas-org", [("acme.example", "verified"), ("other.example", "pending")]
            ),
        )

    made, recorder = provider(found)
    org = await made.ensure_organization(external_id="tadas-org", name="Acme")
    assert org.id == "org_1" and org.verified_domains == ("acme.example",)
    assert len(recorder.requests) == 1

    def missing(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={"message": "not found"})
        assert body_of(request) == {"name": "Acme", "external_id": "tadas-org"}
        return httpx.Response(201, json=organization("org_2", "tadas-org", []))

    made, recorder = provider(missing)
    org = await made.ensure_organization(external_id="tadas-org", name="Acme")
    assert org.id == "org_2" and org.verified_domains == ()
    assert [r.method for r in recorder.requests] == ["GET", "POST"]


async def test_invitations_are_sent_found_and_read_back() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/user_management/invitations":
            assert body_of(request) == {
                "email": "bob@acme.example",
                "organization_id": "org_1",
                "expires_in_days": 7,
            }
            return httpx.Response(201, json=invitation("inv_1", "pending"))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        invitation("inv_0", "revoked"),
                        invitation("inv_1", "accepted", "user_1"),
                        invitation("inv_2", "pending"),
                    ],
                    "list_metadata": {"before": None, "after": None},
                },
            )
        return httpx.Response(404, json={"message": "no"})

    made, _ = provider(answer)
    sent = await made.send_invitation(
        email="bob@acme.example", organization_id="org_1", expires_in_days=7
    )
    assert sent.id == "inv_1" and sent.state is InvitationState.PENDING
    pending = await made.find_pending_invitation(email="bob@acme.example", organization_id="org_1")
    assert pending is not None and pending.id == "inv_2"
    accepted = await made.accepted_invitation(organization_id="org_1", user_id="user_1")
    assert accepted is not None and accepted.id == "inv_1"
    assert await made.accepted_invitation(organization_id="org_1", user_id="user_9") is None


async def test_the_admin_portal_link_is_for_the_organization_and_the_intent() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert body_of(request) == {
            "organization": "org_1",
            "intent": "sso",
            "return_url": "http://localhost:55173/settings",
        }
        return httpx.Response(201, json={"link": "https://setup.example/portal/abc"})

    made, _ = provider(answer)
    link = await made.portal_link(
        organization_id="org_1", intent="sso", return_url="http://localhost:55173/settings"
    )
    assert link == "https://setup.example/portal/abc"


def test_the_client_never_takes_a_credential_from_the_environment() -> None:
    with pytest.raises(ValueError):
        IdentityProviderWorkOSImpl(client_id=CLIENT_ID, api_key="", timeout=timedelta(seconds=1))
    with pytest.raises(ValueError):
        IdentityProviderWorkOSImpl(client_id="", api_key=API_KEY, timeout=timedelta(seconds=1))
