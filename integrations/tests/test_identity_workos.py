"""The WorkOS client over a fake transport: the requests it sends, and every
answer translated into the integration's own shapes and exceptions."""

import base64
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from workos import AsyncWorkOSClient

from tadas.integrations.exceptions import (
    DeviceDenied,
    DeviceExpired,
    DevicePending,
    DeviceSlowDown,
    ProviderConflict,
    ProviderRefused,
    ProviderUnavailable,
    UnsafeIntegration,
)
from tadas.integrations.identity import InvitationState
from tadas.integrations.identity.workos import CREDENTIAL_CHECK_CODE, IdentityProviderWorkOSImpl

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


def access_token(claims: dict[str, Any]) -> str:
    """A token in the shape WorkOS answers: header, claims, signature."""

    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


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


async def test_a_code_is_exchanged_with_the_applications_key_and_its_verifier() -> None:
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
    # A confidential client: the application's key is the client secret,
    # and the verifier goes with it, which WorkOS checks as well.
    assert body["client_id"] == CLIENT_ID and body["client_secret"] == API_KEY
    assert body["code_verifier"] == "the-verifier" and body["invitation_token"] == "inv"


async def test_a_code_sign_in_names_the_authkit_session_its_access_token_carries() -> None:
    made, _ = provider(
        lambda r: httpx.Response(
            200,
            json={
                "user": USER,
                "access_token": access_token({"sub": "user_1", "sid": "session_01ABC"}),
                "refresh_token": "rt",
            },
        )
    )
    signed_in = await made.authenticate_code("c", code_verifier="v")
    assert signed_in.session_id == "session_01ABC"


@pytest.mark.parametrize("token", ["at", "a.!!!.c", access_token({"sub": "user_1"})])
async def test_a_token_with_no_session_to_read_still_signs_in(token: str) -> None:
    made, _ = provider(
        lambda r: httpx.Response(
            200, json={"user": USER, "access_token": token, "refresh_token": "rt"}
        )
    )
    signed_in = await made.authenticate_code("c", code_verifier="v")
    assert signed_in.user.id == "user_1" and signed_in.session_id is None


async def test_a_device_sign_in_keeps_no_browser_session() -> None:
    made, _ = provider(
        lambda r: httpx.Response(
            200,
            json={
                "user": USER,
                "access_token": access_token({"sub": "user_1", "sid": "session_01DEV"}),
                "refresh_token": "rt",
            },
        )
    )
    signed_in = await made.authenticate_device("dev-code")
    assert signed_in.session_id is None


def test_the_logout_url_ends_the_session_and_returns_to_the_portal() -> None:
    made, recorder = provider(lambda r: httpx.Response(500))
    url = made.logout_url(
        session_id="session_01ABC", return_to="https://app.example.test/signed-out"
    )
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "api.workos.com",
        "/user_management/sessions/logout",
    )
    assert query == {
        "session_id": "session_01ABC",
        "return_to": "https://app.example.test/signed-out",
    }
    assert API_KEY not in url and recorder.requests == []
    bare = parse_qs(urlsplit(made.logout_url(session_id="s", return_to=None)).query)
    assert bare == {"session_id": ["s"]}


async def test_a_key_workos_refuses_as_the_applications_is_unavailable_not_the_persons() -> None:
    made, _ = provider(
        lambda r: httpx.Response(
            400, json={"error": "invalid_client", "error_description": "Invalid client secret."}
        )
    )
    with pytest.raises(ProviderUnavailable) as raised:
        await made.authenticate_code("c", code_verifier="v")
    assert "TADAS_WORKOS_API_KEY" in str(raised.value) and API_KEY not in str(raised.value)


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
    # WorkOS takes the device sign-in as a public client's: no secret in it.
    assert body["client_id"] == CLIENT_ID and "client_secret" not in body


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
    assert body_of(recorder.requests[0]) == {"client_id": CLIENT_ID}


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


DEVICE = {
    "device_code": "dc",
    "user_code": "ABCD-EFGH",
    "verification_uri": "https://auth.example/device",
    "expires_in": 300,
}


def sent_with(seconds: float) -> dict[str, float]:
    """The timeout a request carries to the transport, as httpx names it."""
    return {"connect": seconds, "read": seconds, "write": seconds, "pool": seconds}


@pytest.mark.parametrize(("setting", "sent"), [(10.0, 10), (2.5, 3), (0.2, 1)])
async def test_every_call_is_sent_with_the_timeout_from_settings(
    monkeypatch: pytest.MonkeyPatch, setting: float, sent: int
) -> None:
    """The SDK names a timeout on every request, and it overrides the one of
    the HTTP client it is handed. It takes whole seconds, so the setting is
    rounded up, never down to none; the environment's is never read."""
    monkeypatch.setenv("WORKOS_REQUEST_TIMEOUT", "60")
    recorder = Recorder(lambda r: httpx.Response(200, json=DEVICE))
    made = IdentityProviderWorkOSImpl(
        client_id=CLIENT_ID,
        api_key=API_KEY,
        timeout=timedelta(seconds=setting),
        max_retries=0,
        transport=httpx.MockTransport(recorder),
    )
    await made.start_device()
    [request] = recorder.requests
    assert request.extensions["timeout"] == sent_with(sent)


async def test_a_call_that_times_out_is_tried_again_each_time_under_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK's three retries take a timeout too, so a WorkOS that hangs
    costs four attempts of the timeout, and the call is then unavailable."""

    def no_wait(attempt: int, retry_after: str | None = None) -> float:
        return 0.0

    monkeypatch.setattr(AsyncWorkOSClient, "_calculate_retry_delay", staticmethod(no_wait))

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    recorder = Recorder(hang)
    made = IdentityProviderWorkOSImpl(
        client_id=CLIENT_ID,
        api_key=API_KEY,
        timeout=timedelta(seconds=10),
        transport=httpx.MockTransport(recorder),
    )
    with pytest.raises(ProviderUnavailable):
        await made.start_device()
    assert [r.extensions["timeout"] for r in recorder.requests] == [sent_with(10)] * 4


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

    made, recorder = provider(answer)
    sent = await made.send_invitation(
        email="bob@acme.example", organization_id="org_1", expires_in_days=7
    )
    assert sent.id == "inv_1" and sent.state is InvitationState.PENDING
    pending = await made.find_pending_invitation(email="bob@acme.example", organization_id="org_1")
    assert pending is not None and pending.id == "inv_2"
    accepted = await made.accepted_invitation(
        organization_id="org_1", user_id="user_1", email="bob@acme.example"
    )
    assert accepted is not None and accepted.id == "inv_1"
    assert (
        await made.accepted_invitation(
            organization_id="org_1", user_id="user_9", email="bob@acme.example"
        )
        is None
    )
    # Every management call carries the application's key, so an invitation
    # is sent in the application's context and lands its person there.
    assert {r.headers["authorization"] for r in recorder.requests} == {f"Bearer {API_KEY}"}


async def test_the_accepted_invitation_is_read_by_the_persons_address_first() -> None:
    """One page of the invitations sent to the address; the organization's
    others only when none of those is the one, since an invitation to a
    company's domain may be accepted with another address of it."""

    def answer(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        by_address = query.get("email") == ["bob@acme.example"]
        data = (
            [invitation("inv_1", "accepted", "user_1")]
            if by_address
            else [invitation("inv_2", "accepted", "user_2")]
        )
        return httpx.Response(
            200,
            json={"object": "list", "data": data, "list_metadata": {"before": None, "after": None}},
        )

    made, recorder = provider(answer)
    accepted = await made.accepted_invitation(
        organization_id="org_1", user_id="user_1", email="bob@acme.example"
    )
    assert accepted is not None and accepted.id == "inv_1"
    [only] = recorder.requests
    assert only.url.path == "/user_management/invitations"
    assert parse_qs(only.url.query.decode()) == {
        "organization_id": ["org_1"],
        "email": ["bob@acme.example"],
        "limit": ["100"],
        "order": ["desc"],
    }

    made, recorder = provider(answer)
    accepted = await made.accepted_invitation(
        organization_id="org_1", user_id="user_2", email="bob@acme.example"
    )
    assert accepted is not None and accepted.id == "inv_2"
    first, second = (parse_qs(r.url.query.decode()) for r in recorder.requests)
    assert first["email"] == ["bob@acme.example"] and "email" not in second
    assert second["organization_id"] == ["org_1"]


async def test_the_admin_portal_link_is_for_the_organization_and_the_intent() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert body_of(request) == {
            "organization": "org_1",
            "intent": "sso",
            "return_url": "http://localhost:55173/settings",
        }
        return httpx.Response(201, json={"link": "https://setup.example/portal/abc"})

    made, recorder = provider(answer)
    link = await made.portal_link(
        organization_id="org_1", intent="sso", return_url="http://localhost:55173/settings"
    )
    assert link == "https://setup.example/portal/abc"
    assert recorder.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_the_client_never_takes_a_credential_from_the_environment() -> None:
    with pytest.raises(ValueError):
        IdentityProviderWorkOSImpl(client_id=CLIENT_ID, api_key="", timeout=timedelta(seconds=1))
    with pytest.raises(ValueError):
        IdentityProviderWorkOSImpl(client_id="", api_key=API_KEY, timeout=timedelta(seconds=1))


def credential_check(
    status: int, error: str | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user_management/authenticate"
        return httpx.Response(status, json={"error": error, "error_description": "said"})

    return answer


async def test_the_start_proves_the_key_is_the_applications() -> None:
    made, recorder = provider(credential_check(400, "invalid_grant"))
    await made.start()
    [sent] = recorder.requests
    body = body_of(sent)
    # A code WorkOS never issued, exchanged as the application: only the
    # application's own key gets as far as the code.
    assert body["code"] == CREDENTIAL_CHECK_CODE and "code_verifier" not in body
    assert body["client_id"] == CLIENT_ID and body["client_secret"] == API_KEY


async def test_the_start_refuses_a_key_of_another_application_or_environment() -> None:
    made, _ = provider(credential_check(400, "invalid_client"))
    with pytest.raises(UnsafeIntegration) as raised:
        await made.start()
    message = str(raised.value)
    assert "TADAS_WORKOS_API_KEY" in message and CLIENT_ID in message
    assert "API keys" in message and API_KEY not in message


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_the_start_goes_on_when_workos_cannot_say(status: int) -> None:
    made, _ = provider(credential_check(status))
    await made.start()


async def test_the_start_goes_on_when_workos_is_out_of_reach() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    made, _ = provider(refuse)
    await made.start()


async def test_a_user_is_deleted_by_the_subject_and_a_gone_one_is_done() -> None:
    made, recorder = provider(lambda r: httpx.Response(204))
    await made.delete_user("user_01ABC")
    [asked] = recorder.requests
    assert (asked.method, asked.url.path) == ("DELETE", "/user_management/users/user_01ABC")
    gone, _ = provider(lambda r: httpx.Response(404, json={"message": "not found"}))
    await gone.delete_user("user_01ABC")  # deleted already: a rerun is one deletion


@pytest.mark.parametrize("status", [503, 401, 403])
async def test_a_deletion_workos_cannot_take_now_or_from_this_key_is_unavailable(
    status: int,
) -> None:
    """A server error, and a refusal of the process's own key, which a person
    fixes: the work that asked waits for either."""
    made, _ = provider(lambda r: httpx.Response(status, json={"message": "no"}))
    with pytest.raises(ProviderUnavailable) as raised:
        await made.delete_user("user_01ABC")
    assert API_KEY not in str(raised.value)


async def test_a_deletion_workos_refuses_as_a_request_is_refused() -> None:
    refused, _ = provider(lambda r: httpx.Response(400, json={"message": "bad id"}))
    with pytest.raises(ProviderRefused):
        await refused.delete_user("not-an-id")


async def test_an_organization_is_deleted_by_its_id_and_a_gone_one_is_done() -> None:
    made, recorder = provider(lambda r: httpx.Response(202))
    await made.delete_organization("org_01ABC")
    [asked] = recorder.requests
    assert (asked.method, asked.url.path) == ("DELETE", "/organizations/org_01ABC")
    gone, _ = provider(lambda r: httpx.Response(404, json={"message": "not found"}))
    await gone.delete_organization("org_01ABC")  # deleted already: a rerun is one deletion


@pytest.mark.parametrize("status", [503, 401, 403])
async def test_an_organization_workos_cannot_delete_now_or_from_this_key_is_unavailable(
    status: int,
) -> None:
    made, _ = provider(lambda r: httpx.Response(status, json={"message": "no"}))
    with pytest.raises(ProviderUnavailable) as raised:
        await made.delete_organization("org_01ABC")
    assert API_KEY not in str(raised.value)


async def test_an_organization_workos_refuses_to_delete_is_refused() -> None:
    refused, _ = provider(lambda r: httpx.Response(400, json={"message": "bad id"}))
    with pytest.raises(ProviderRefused):
        await refused.delete_organization("not-an-id")
