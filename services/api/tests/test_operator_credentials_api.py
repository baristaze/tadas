"""The operator plane's credentials over the live app: the second factor an
operator enrols before the plane admits them, the operator token an agent
presents instead of a password, the audited password reset, and the grant
job's command."""

import argparse
from uuid import UUID

import httpx
import pytest
from api_support import bearer, code_at, enrol_operator, secret_of, seed_request, sign_in_as

from tadas.om.opcontext import OperatorRole
from tadas.om.tenancy.rules import email_digest
from tadas.services.api import main as api_main
from tadas.services.api.container import AppContainer
from tadas.services.api.settings import ApiSettings
from tadas.services.api.token_secrets import token_secret_name


async def test_an_operator_enrols_a_second_factor_before_the_plane_admits_them(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    await container.managers.tenancy.bootstrap(
        seed_request(),
        "Root",
        "root",
        "root@example.test",
        "pw-1234",
        "Root",
        operator_role=OperatorRole.WRITE,
    )
    first = await client.post(
        "/v1/auth/login", json={"email": "root@example.test", "password": "pw-1234"}
    )
    enrolling = bearer(first.json()["token"])
    # Allowlisted, no factor yet: every route but the two enrolment ones refuses.
    for path in ("/v1/admin/me", "/v1/admin/orgs", "/v1/admin/size"):
        refused = await client.get(path, headers=enrolling)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "second_factor_not_enrolled"
    minted = await client.post("/v1/admin/me/totp", headers=enrolling)
    assert minted.status_code == 200, minted.text
    uri = minted.json()["otpauth_uri"]
    assert uri.startswith("otpauth://totp/Tadas%3Aroot%40example.test?secret=")
    secret = secret_of(uri)
    wrong = await client.post(
        "/v1/admin/me/totp/confirm", headers=enrolling, json={"totp_code": "000000"}
    )
    assert wrong.status_code == 422, wrong.text
    confirmed = await client.post(
        "/v1/admin/me/totp/confirm", headers=enrolling, json={"totp_code": code_at(secret, 0)}
    )
    assert confirmed.status_code == 200, confirmed.text

    # Enrolled: the sign-in that carried no code no longer admits.
    required = await client.get("/v1/admin/me", headers=enrolling)
    assert required.status_code == 401, required.text
    assert required.json()["error"]["code"] == "second_factor_required"
    body = {"email": "root@example.test", "password": "pw-1234"}
    bad = await client.post("/v1/auth/login", json=body | {"totp_code": "000000"})
    assert bad.status_code == 401, bad.text
    code = code_at(secret, 1)
    login = await client.post("/v1/auth/login", json=body | {"totp_code": code})
    assert login.status_code == 200, login.text
    signed_in = bearer(login.json()["token"])
    admitted = await client.get("/v1/admin/me", headers=signed_in)
    assert admitted.status_code == 200 and admitted.json()["operator_role"] == "write"
    again = await client.post("/v1/admin/me/totp", headers=signed_in)
    assert again.status_code == 409, again.text
    reused = await client.post("/v1/auth/login", json=body | {"totp_code": code})
    assert reused.status_code == 401, reused.text


async def test_an_operator_token_is_minted_once_and_admits_with_its_one_permission(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    writer, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    mint = {**writer, "Idempotency-Key": "token-1"}
    issued = await client.post("/v1/admin/me/tokens", headers=mint, json={"permission": "read"})
    assert issued.status_code == 201, issued.text
    token = issued.json()["token"]
    assert token.startswith("opr_") and issued.json()["permission"] == "read"
    replay = await client.post("/v1/admin/me/tokens", headers=mint, json={"permission": "read"})
    assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["token"] is None, "shown once"

    agent = bearer(token)
    me = await client.get("/v1/admin/me", headers=agent)
    assert me.status_code == 200, me.text
    assert me.json()["operator_role"] == "read" and me.json()["email"] == "root@example.test"
    assert (await client.get("/v1/admin/orgs", headers=agent)).status_code == 200
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    write = await client.delete(f"/v1/admin/orgs/{org_id}", headers=agent)
    assert write.status_code == 403, write.text
    # A token never mints a token, and reaches no tenant and no person's places.
    minted_by_token = await client.post(
        "/v1/admin/me/tokens", headers=agent, json={"permission": "read"}
    )
    assert minted_by_token.status_code == 403, minted_by_token.text
    assert (await client.get("/v1/me", headers=agent)).status_code == 401
    assert (await client.get("/v1/auth/memberships", headers=agent)).status_code == 401
    exchanged = await client.post("/v1/auth/sessions", headers=agent, json={"org_id": org_id})
    assert exchanged.status_code == 401, exchanged.text
    # An hour at most, and never wider than the entry.
    long = await client.post(
        "/v1/admin/me/tokens", headers=writer, json={"permission": "read", "expires_in": 3601}
    )
    assert long.status_code == 422, long.text
    reader, _ = await enrol_operator(client, container, "sup@example.test", OperatorRole.READ)
    wider = await client.post("/v1/admin/me/tokens", headers=reader, json={"permission": "write"})
    assert wider.status_code == 403, wider.text


async def test_an_operator_resets_a_password_and_the_reset_is_audited(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    writer, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    reader, _ = await enrol_operator(client, container, "sup@example.test", OperatorRole.READ)
    body = {"email": "ann@example.test", "password": "a-new-password"}
    refused = await client.post("/v1/admin/password-resets", headers=reader, json=body)
    assert refused.status_code == 403, refused.text
    reset = await client.post("/v1/admin/password-resets", headers=writer, json=body)
    assert reset.status_code == 200, reset.text
    assert reset.json()["email"] == "ann@example.test" and UUID(reset.json()["identity_id"])
    old = await client.post(
        "/v1/auth/login", json={"email": "ann@example.test", "password": "pw-1234"}
    )
    assert old.status_code == 401
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    assert await sign_in_as(client, "ann@example.test", "a-new-password", UUID(org_id))


def grant_args(**given: object) -> argparse.Namespace:
    return argparse.Namespace(
        **({"permission": None, "disable": False, "mint_token": None, "expires_in": None} | given)
    )


async def test_the_grant_command_grants_disables_and_mints_into_the_secret_store(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tenancy = container.managers.tenancy
    await tenancy.bootstrap(seed_request(), "Acme", "acme", "ann@example.test", "pw-1234", "Ann")
    settings = container.settings
    await api_main.granted(
        container, settings, grant_args(email="ann@example.test", permission="read")
    )
    storage = container.storage.get_tenancy_storage()
    ann = await storage.read_identity_by_email_digest(email_digest("ann@example.test"))
    assert ann is not None and ann.operator_role is OperatorRole.READ
    await api_main.granted(container, settings, grant_args(email="ann@example.test", disable=True))
    ann = await storage.read_identity_by_email_digest(email_digest("ann@example.test"))
    assert ann is not None and ann.operator_role is None

    # The platform's own identity is made by its first grant, and its token
    # goes to the secret store in the cloud and nowhere else.
    provisioner = "provisioner@platform.tadas.invalid"
    await api_main.granted(container, settings, grant_args(email=provisioner, permission="write"))
    written: list[tuple[str, str]] = []

    async def put(_: ApiSettings, name: str, token: str) -> None:
        written.append((name, token))

    monkeypatch.setattr(api_main, "put_token", put)
    cloud = settings.model_copy(update={"environment": "staging"})
    for holder in ("provisioner", "smoke"):
        await api_main.granted(
            container, cloud, grant_args(email=provisioner, mint_token=holder, expires_in=600)
        )
    assert [name for name, _ in written] == [
        "tadas-staging-provisioner-token",
        "tadas-staging-smoke-token",
    ]
    assert all(token.startswith("opr_") for _, token in written)
    assert "opr_" not in capsys.readouterr().out, "never printed in the cloud"
    smoke = await tenancy.admit_operator(
        await tenancy.authenticate_login(seed_request(), written[1][1])
    )
    assert {p.value for p in smoke.permissions} == {"read"}, "the smoke test only reads"
    assert token_secret_name("production", "smoke") == "tadas-production-smoke-token"


def test_the_grant_command_names_its_identity_and_one_action() -> None:
    for argv in (
        ["grant-operator", "--permission", "read"],
        ["grant-operator", "--email", "a@example.test"],
        ["grant-operator", "--email", "a@example.test", "--permission", "read", "--disable"],
        ["grant-operator", "--email", "a@example.test", "--mint-token", "other"],
        [
            "grant-operator",
            "--email",
            "a@example.test",
            "--permission",
            "read",
            "--expires-in",
            "5",
        ],
    ):
        with pytest.raises(SystemExit):
            api_main.main(argv)
