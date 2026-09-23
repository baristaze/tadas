"""The integrations root picks the provider from settings, and refuses the
twin anywhere but a local environment."""

import pytest

from tadas.integrations.exceptions import ProviderUnavailable, UnsafeIntegration
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.identity.twin import IdentityProviderTwinImpl
from tadas.integrations.identity.workos import IdentityProviderWorkOSImpl
from tadas.integrations.impl.configured import IntegrationsConfiguredImpl, absent_integrations
from tadas.integrations.settings import IntegrationsSettings

DEPLOYED = frozenset({"dev", "staging", "production"})


def settings(**values: object) -> IntegrationsSettings:
    return IntegrationsSettings.model_validate({"_env_file": None, **values})


@pytest.mark.parametrize("environment", ["dev", "staging", "production"])
def test_the_twin_is_refused_in_a_deployed_environment(environment: str) -> None:
    with pytest.raises(UnsafeIntegration, match="TADAS_IDENTITY_PROVIDER=twin"):
        IntegrationsConfiguredImpl(
            settings(identity_provider="twin"), environment, environment in DEPLOYED
        )


@pytest.mark.parametrize("environment", ["local", "test"])
def test_the_twin_runs_locally(environment: str) -> None:
    root = IntegrationsConfiguredImpl(
        settings(identity_provider="twin"), environment, environment in DEPLOYED
    )
    assert isinstance(root.get_identity_provider(), IdentityProviderTwinImpl)


@pytest.mark.parametrize("key", [None, "", "off", " OFF "])
def test_workos_without_its_key_is_absent(key: str | None) -> None:
    root = IntegrationsConfiguredImpl(
        settings(identity_provider="workos", workos_client_id="client_x", workos_api_key=key),
        "staging",
        True,
    )
    provider = root.get_identity_provider()
    assert isinstance(provider, IdentityProviderAbsentImpl) and not provider.configured
    assert "TADAS_WORKOS_API_KEY" in provider.describe()


def test_workos_without_its_client_id_is_absent() -> None:
    root = IntegrationsConfiguredImpl(
        settings(identity_provider="workos", workos_api_key="sk_test"), "local", False
    )
    assert "TADAS_WORKOS_CLIENT_ID" in root.get_identity_provider().describe()


def test_workos_with_both_is_the_real_client_and_says_so_without_the_key() -> None:
    root = IntegrationsConfiguredImpl(
        settings(
            identity_provider="workos", workos_client_id="client_x", workos_api_key="sk_secret"
        ),
        "staging",
        True,
    )
    assert isinstance(root.get_identity_provider(), IdentityProviderWorkOSImpl)
    described = " ".join(root.describe())
    assert "client_x" in described and "sk_secret" not in described
    assert "sk_secret" not in repr(settings(identity_provider="workos", workos_api_key="sk_secret"))


def test_no_provider_is_the_default_and_refuses_every_call() -> None:
    root = IntegrationsConfiguredImpl(settings(), "production", True)
    provider = root.get_identity_provider()
    assert not provider.configured
    with pytest.raises(ProviderUnavailable):
        provider.authorization_url(redirect_uri="https://x/cb", state="s", code_challenge="c")


async def test_the_absent_provider_refuses_every_call() -> None:
    absent = IdentityProviderAbsentImpl("closed")
    for call in (
        absent.authenticate_code("c", code_verifier="v"),
        absent.start_device(),
        absent.authenticate_device("d"),
        absent.ensure_organization(external_id="e", name="n"),
        absent.get_organization("o"),
        absent.send_invitation(email="e@x.test", organization_id="o", expires_in_days=1),
        absent.find_pending_invitation(email="e@x.test", organization_id="o"),
        absent.resend_invitation("i"),
        absent.revoke_invitation("i"),
        absent.accepted_invitation(organization_id="o", user_id="u"),
        absent.portal_link(organization_id="o", intent="sso", return_url="https://x"),
    ):
        with pytest.raises(ProviderUnavailable, match="closed"):
            await call
    root = absent_integrations()
    await root.start()
    assert root.describe() == [
        root.get_identity_provider().describe(),
        root.get_payments().describe(),
    ]
    await root.close()
