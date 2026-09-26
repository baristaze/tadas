"""The slack manager over the memory roots and Slack's twin: an install is
bound to the org and the person who started it, works once and only in time,
keeps the token as the org's own secret and nowhere else, and gives a
workspace to one org; an uninstall takes the token away; the token renews
before it expires, one renewal at a time; and a Slack user is matched to a
member by the address their profile holds."""

from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from tadas.infra.exceptions import SecretNotFound
from tadas.infra.impl.local import InfraLocalImpl
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.impl.configured import IntegrationsOverImpl
from tadas.integrations.slack import SlackTokenRevoked
from tadas.integrations.slack.twin import SlackTwinImpl
from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import NotAuthorized, NotFound, SlackWorkspaceTaken
from tadas.om.opcontext import AppContext, AppType, OpContext, RequestContext, Role
from tadas.om.root import Managers, build_managers
from tadas.om.slack.impl.manager import tokens_from, tokens_json
from tadas.om.slack.types.installation import SlackInstallationStatus
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.tenancy.impl.manager import TenancyOptions

APP = AppContext(type=AppType.PORTAL, version="portal@test")
REDIRECT = "https://api.tadas.test/webhooks/slack/oauth"


def request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=APP)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.storage = StorageMemoryImpl()
        self.infra = InfraLocalImpl(tmp_path)
        self.twin = SlackTwinImpl("test")
        self.managers: Managers = build_managers(
            self.storage,
            self.infra,
            TenancyOptions(dev_sign_in=True),
            integrations=IntegrationsOverImpl(IdentityProviderAbsentImpl(), slack=self.twin),
        )

    async def org(self, slug: str) -> OpContext:
        ctx, _ = await self.managers.tenancy.bootstrap(
            request(), slug.title(), slug, f"owner@{slug}.test", "Owner"
        )
        return ctx

    async def member(self, slug: str, email: str, role: Role = Role.MEMBER) -> OpContext:
        tenancy = self.managers.tenancy
        await tenancy.add_member(request(), slug, email, "Member", role)
        login = await tenancy.dev_sign_in(request(), email)
        identity = await tenancy.authenticate_login(request(), login.token)
        memberships = await tenancy.get_identity_memberships(identity, None, 10)
        org = next(m.org.id for m in memberships.items if m.org.slug == slug)
        session = await tenancy.exchange_login(identity, org)
        return await tenancy.authenticate(request(), session.token)

    async def install(self, ctx: OpContext, team: str = "T0ACME") -> str:
        """An owner starts the install, and Slack sends the browser back with
        a code for `team`: answers the state it carried."""
        start = await self.managers.slack.start_install(ctx, REDIRECT)
        state = parse_qs(urlsplit(start.url).query)["state"][0]
        code = self.twin.approve(team, "U0OWNER", "Acme")
        await self.managers.slack.finish_install(request(), state, code, REDIRECT)
        return state


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


async def test_an_install_is_the_orgs_and_its_token_is_the_orgs_secret(world: World) -> None:
    owner = await world.org("acme")
    await world.install(owner)
    installation = await world.managers.slack.get_installation(owner)
    assert installation is not None
    assert installation.team_id == "T0ACME" and installation.created_by == owner.user_id
    assert installation.installed_by_slack_user == "U0OWNER"
    assert installation.channel_id is None
    assert installation.token_expires_at is not None
    stored = tokens_from(
        await world.infra.get_secrets().get(owner.org_id, installation.credential_ref)
    )
    assert world.twin.team_of(stored.access_token.get_secret_value()) == "T0ACME"
    assert "xoxe" not in installation.model_dump_json(), "no token on the row"
    # Another org's name for the secret reads nothing.
    other = await world.org("fabrikam")
    with pytest.raises(SecretNotFound):
        await world.infra.get_secrets().get(other.org_id, installation.credential_ref)


async def test_only_an_owner_or_an_admin_starts_an_install(world: World) -> None:
    await world.org("acme")
    bob = await world.member("acme", "bob@acme.test")
    with pytest.raises(NotAuthorized):
        await world.managers.slack.start_install(bob, REDIRECT)


async def test_a_state_works_once_in_time_and_only_as_issued(world: World) -> None:
    owner = await world.org("acme")
    slack = world.managers.slack
    state = await world.install(owner)
    with pytest.raises(NotFound):  # reused
        await slack.finish_install(request(), state, world.twin.approve("T0ACME", "U1"), REDIRECT)
    with pytest.raises(NotFound):  # forged
        await slack.finish_install(
            request(), "not-a-state", world.twin.approve("T0ACME", "U1"), REDIRECT
        )
    start = await slack.start_install(owner, REDIRECT)
    late = parse_qs(urlsplit(start.url).query)["state"][0]
    stored = world.storage.get_slack_storage()
    for org_id, row in list(stored._states.values()):  # type: ignore[attr-defined]
        stored._states[row.id] = (  # type: ignore[attr-defined]
            org_id,
            row.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)}),
        )
    with pytest.raises(NotFound):  # expired
        await slack.finish_install(request(), late, world.twin.approve("T0ACME", "U1"), REDIRECT)


async def test_a_workspace_is_one_orgs_and_the_second_token_is_revoked(world: World) -> None:
    acme = await world.org("acme")
    fabrikam = await world.org("fabrikam")
    await world.install(acme, "T0SHARED")
    start = await world.managers.slack.start_install(fabrikam, REDIRECT)
    state = parse_qs(urlsplit(start.url).query)["state"][0]
    code = world.twin.approve("T0SHARED", "U0OTHER")
    grant_token = world.twin._codes[code].tokens.access_token.get_secret_value()  # type: ignore[attr-defined]
    with pytest.raises(SlackWorkspaceTaken):
        await world.managers.slack.finish_install(request(), state, code, REDIRECT)
    assert await world.managers.slack.get_installation(fabrikam) is None
    assert world.twin.team_of(grant_token) is None, "the token Tadas will not keep is revoked"
    assert await world.managers.slack.bot_token(acme), "the org holding it keeps working"


async def test_installing_again_keeps_the_channel_and_mends_the_install(world: World) -> None:
    owner = await world.org("acme")
    slack = world.managers.slack
    await world.install(owner)
    await slack.bind_channel(owner, "C0TEAM")
    await slack.mark_broken(owner, "not_in_channel")
    before = await slack.get_installation(owner)
    await world.install(owner)
    after = await slack.get_installation(owner)
    assert before is not None and after is not None
    assert after.id == before.id and after.channel_id == "C0TEAM"
    assert after.status is SlackInstallationStatus.OK and after.broken_reason is None


async def test_another_workspace_replaces_the_first_and_the_app_leaves_it(world: World) -> None:
    owner = await world.org("acme")
    await world.install(owner, "T0FIRST")
    first = await world.managers.slack.get_installation(owner)
    await world.install(owner, "T0SECOND")
    second = await world.managers.slack.get_installation(owner)
    assert first is not None and second is not None and second.team_id == "T0SECOND"
    assert world.twin.uninstalled == ["T0FIRST"]
    assert not await world.infra.get_secrets().has(owner.org_id, first.credential_ref)


async def test_an_uninstall_removes_the_app_and_the_token(world: World) -> None:
    owner = await world.org("acme")
    await world.install(owner)
    installation = await world.managers.slack.get_installation(owner)
    assert installation is not None
    gone = await world.managers.slack.uninstall(owner)
    assert gone is not None and gone.deleted_at is not None
    assert world.twin.uninstalled == ["T0ACME"]
    assert await world.managers.slack.get_installation(owner) is None
    assert not await world.infra.get_secrets().has(owner.org_id, installation.credential_ref)
    assert await world.managers.slack.uninstall(owner) is None


async def test_forgetting_leaves_slack_alone(world: World) -> None:
    owner = await world.org("acme")
    await world.install(owner)
    assert await world.managers.slack.forget(owner, "app_uninstalled") is not None
    assert world.twin.uninstalled == []
    assert await world.managers.slack.get_installation(owner) is None


async def test_a_token_renews_before_it_expires_one_renewal_at_a_time(world: World) -> None:
    owner = await world.org("acme")
    slack = world.managers.slack
    await world.install(owner)
    first = await slack.bot_token(owner)
    assert await slack.bot_token(owner) == first, "a fresh token is used as it is"
    installation = await slack.get_installation(owner)
    assert installation is not None
    secrets = world.infra.get_secrets()
    stored = tokens_from(await secrets.get(owner.org_id, installation.credential_ref))
    soon = stored.model_copy(update={"expires_at": utcnow() + timedelta(minutes=5)})
    await secrets.put(owner.org_id, installation.credential_ref, tokens_json(soon))
    # Another caller holds the renewal: this one keeps the token that still works.
    storage = world.storage.get_slack_storage()
    now = utcnow()
    assert await storage.claim_refresh(owner.org_id, installation.id, now, now + timedelta(30))
    assert await slack.bot_token(owner) == first
    await storage.settle_refresh(owner.org_id, installation.id, soon.expires_at, now)
    renewed = await slack.bot_token(owner)
    assert renewed != first and world.twin.team_of(renewed) == "T0ACME"
    after = await slack.get_installation(owner)
    assert after is not None and after.refreshing_until is None
    assert after.token_expires_at is not None and after.token_expires_at > now + timedelta(hours=11)
    # The refresh token it used works once.
    with pytest.raises(SlackTokenRevoked):
        await world.twin.refresh(stored.refresh_token.get_secret_value())  # type: ignore[union-attr]


async def test_a_token_that_no_longer_renews_breaks_the_install(world: World) -> None:
    owner = await world.org("acme")
    slack = world.managers.slack
    await world.install(owner)
    installation = await slack.get_installation(owner)
    assert installation is not None
    secrets = world.infra.get_secrets()
    stored = tokens_from(await secrets.get(owner.org_id, installation.credential_ref))
    await secrets.put(
        owner.org_id,
        installation.credential_ref,
        tokens_json(stored.model_copy(update={"expires_at": utcnow()})),
    )
    world.twin.revoke_team("T0ACME")
    with pytest.raises(SlackTokenRevoked):
        await slack.bot_token(owner)
    broken = await slack.get_installation(owner)
    assert broken is not None and broken.status is SlackInstallationStatus.BROKEN
    assert broken.broken_reason == "invalid_refresh_token"


def counted_secrets(world: World, monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """How many times the org's secrets were asked, by call."""
    secrets = world.infra.get_secrets()
    calls: Counter[str] = Counter()
    for name in ("get", "has"):
        real = getattr(secrets, name)

        async def call(*args: Any, _real: Any = real, _name: str = name, **kw: Any) -> Any:
            calls[_name] += 1
            return await _real(*args, **kw)

        monkeypatch.setattr(secrets, name, call)
    return calls


async def test_a_bot_token_is_one_read_of_the_orgs_secrets(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await world.org("acme")
    await world.install(owner)
    calls = counted_secrets(world, monkeypatch)
    assert await world.managers.slack.bot_token(owner)
    assert calls == {"get": 1}


async def test_a_token_gone_from_the_secrets_breaks_the_install(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await world.org("acme")
    slack = world.managers.slack
    await world.install(owner)
    installation = await slack.get_installation(owner)
    assert installation is not None
    await world.infra.get_secrets().delete(owner.org_id, installation.credential_ref)
    calls = counted_secrets(world, monkeypatch)
    with pytest.raises(SlackTokenRevoked, match="token_missing"):
        await slack.bot_token(owner)
    assert calls == {"get": 1}
    broken = await slack.get_installation(owner)
    assert broken is not None and broken.status is SlackInstallationStatus.BROKEN
    assert broken.broken_reason == "token_missing"
    # An uninstall with no token leaves Slack alone and still removes the row.
    calls.clear()
    assert await slack.uninstall(owner) is not None
    assert calls == {"get": 1}
    assert world.twin.uninstalled == []
    assert await slack.get_installation(owner) is None


async def test_a_slack_user_is_matched_to_a_member_by_address(world: World) -> None:
    owner = await world.org("acme")
    await world.org("fabrikam")
    bob = await world.member("acme", "bob@acme.test")
    tenancy = world.managers.tenancy
    found = await tenancy.member_context(request(), owner.org_id, "Bob@Acme.test")
    assert found is not None and found.user_id == bob.user_id and found.role is Role.MEMBER
    owner_found = await tenancy.member_context(request(), owner.org_id, "owner@acme.test")
    assert owner_found is not None and owner_found.role is Role.OWNER
    assert await tenancy.member_context(request(), owner.org_id, "nobody@acme.test") is None
    # A person of another org is nobody here.
    assert await tenancy.member_context(request(), owner.org_id, "owner@fabrikam.test") is None
