from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import UUID

from tadas.om.base import EMPTY_UUID
from tadas.om.exceptions import Conflict, NotFound, UniqueKeyTaken
from tadas.om.idempotency.storage import AttemptFenceInterface
from tadas.om.outbox.storage import OutboxLandingInterface
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.storage.impl.memory_base import HasId, MemoryStorageBase, MemoryTable
from tadas.om.tenancy.rules import email_digest as digest_of
from tadas.om.tenancy.rules import is_after_in_id_order, is_after_newest_first
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.issued import OrgMembership
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.session import Session
from tadas.om.tenancy.types.sign_in_delay import SignInDelay
from tadas.om.tenancy.types.socket_ticket import SocketTicket
from tadas.om.tenancy.types.user import User


class TenancyStorageMemoryImpl(MemoryStorageBase, TenancyStorageInterface):
    def __init__(
        self,
        outbox: OutboxLandingInterface | None = None,
        markers: AttemptFenceInterface | None = None,
    ) -> None:
        super().__init__(outbox)
        self._markers = markers
        self._identities: dict[UUID, Identity] = {}
        self._sign_in_delays: dict[str, SignInDelay] = {}
        self._orgs: MemoryTable[Org] = {}
        self._users: MemoryTable[User] = {}
        self._memberships: MemoryTable[Membership] = {}
        self._sessions: MemoryTable[Session] = {}
        self._api_keys: MemoryTable[ApiKey] = {}
        self._socket_tickets: MemoryTable[SocketTicket] = {}

    @staticmethod
    def _require_free[E: HasId](
        rows: Iterable[E], entity: E, taken_by: Callable[[E], bool], key: str
    ) -> None:
        """The memory twin of a unique index: refuses the write when another row
        (never the entity's own, so an update by copy passes) holds the key."""
        for other in rows:
            if other.id != entity.id and taken_by(other):
                raise UniqueKeyTaken(f"{key} is taken")

    async def read_identity(self, identity_id: UUID) -> Identity | None:
        return self._identities.get(identity_id)

    async def read_identity_by_email_digest(self, email_digest: str) -> Identity | None:
        return next(
            (i for i in self._identities.values() if digest_of(i.email) == email_digest),
            None,
        )

    async def write_identity(
        self, identity: Identity, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        async with self._lock:
            self._require_email_free(identity)
            self._land(EMPTY_UUID, outbox_rows)
            self._identities[identity.id] = identity

    async def _update_identity(
        self, identity_id: UUID, when: Callable[[Identity], bool], **values: object
    ) -> bool:
        """The twin of one conditional UPDATE on an identity."""
        async with self._lock:
            identity = self._identities.get(identity_id)
            if identity is None or not when(identity):
                return False
            self._identities[identity_id] = identity.model_copy(update=values)
            return True

    async def write_totp_secret(self, identity_id: UUID, sealed: str, at: datetime) -> bool:
        return await self._update_identity(
            identity_id,
            lambda i: i.totp_confirmed_at is None,
            totp_secret=sealed,
            totp_last_step=None,
            updated_at=at,
        )

    async def confirm_totp(self, identity_id: UUID, step: int, at: datetime) -> bool:
        return await self._update_identity(
            identity_id,
            lambda i: i.totp_secret is not None and i.totp_confirmed_at is None,
            totp_confirmed_at=at,
            totp_last_step=step,
            updated_at=at,
        )

    async def use_totp_step(self, identity_id: UUID, step: int) -> bool:
        return await self._update_identity(
            identity_id,
            lambda i: (
                i.totp_confirmed_at is not None
                and (i.totp_last_step is None or i.totp_last_step < step)
            ),
            totp_last_step=step,
        )

    async def read_sign_in_delay(self, email_digest: str) -> SignInDelay | None:
        return self._sign_in_delays.get(email_digest)

    async def record_failed_sign_in(self, email_digest: str, at: datetime) -> None:
        async with self._lock:
            run = self._sign_in_delays.get(email_digest)
            self._sign_in_delays[email_digest] = SignInDelay(
                email_digest=email_digest,
                failures=1 if run is None else run.failures + 1,
                last_failed_at=at,
            )

    async def clear_failed_sign_ins(self, email_digest: str) -> None:
        self._sign_in_delays.pop(email_digest, None)

    async def purge_sign_in_delays(self, before: datetime) -> int:
        gone = [key for key, run in self._sign_in_delays.items() if run.last_failed_at < before]
        for key in gone:
            del self._sign_in_delays[key]
        return len(gone)

    def _require_email_free(self, identity: Identity) -> None:
        self._require_free(
            self._identities.values(),
            identity,
            lambda other: other.email == identity.email,
            "uq_identities_email",
        )

    async def read_org(self, org_id: UUID) -> Org | None:
        return self._get(self._orgs, org_id, org_id)

    async def read_org_by_slug(self, slug: str) -> Org | None:
        return next(
            (org for _, org in self._orgs.values() if org.slug == slug and org.deleted_at is None),
            None,
        )

    async def count_orgs(self) -> int:
        return sum(1 for org in self._every(self._orgs) if org.deleted_at is None)

    async def count_users(self) -> int:
        return sum(1 for user in self._every(self._users) if user.deleted_at is None)

    async def read_orgs(self, limit: int, after_id: UUID | None = None) -> list[Org]:
        orgs = [org for _, org in self._rows_across_tenants(self._orgs)]
        if after_id is not None:
            orgs = [org for org in orgs if org.id > after_id]
        return orgs[:limit]

    async def write_org(
        self, org_id: UUID, org: Org, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        self._require_slug_free(org)
        self._put(self._orgs, org_id, org, outbox_rows)

    def _require_slug_free(self, org: Org) -> None:
        # uq_orgs_slug: unique among the living, so a deleted org frees its slug.
        if org.deleted_at is None:
            self._require_free(
                self._every(self._orgs),
                org,
                lambda other: other.slug == org.slug and other.deleted_at is None,
                "uq_orgs_slug",
            )
        # uq_orgs_personal_identity_id: one living personal org per person.
        if org.personal and org.deleted_at is None:
            self._require_free(
                self._every(self._orgs),
                org,
                lambda other: (
                    other.personal
                    and other.personal_identity_id == org.personal_identity_id
                    and other.deleted_at is None
                ),
                "uq_orgs_personal_identity_id",
            )

    async def create_org_with_owner(
        self,
        org_id: UUID,
        org: Org,
        user: User,
        membership: Membership,
        identity: Identity | None = None,
        personal: tuple[Org, User, Membership] | None = None,
    ) -> None:
        # Every check, then every write: the twin of one commit.
        async with self._lock:
            if identity is not None:
                self._require_email_free(identity)
            if personal is not None:
                self._require_tenant_free(personal[0].id, *personal)
            self._require_tenant_free(org_id, org, user, membership)
            if identity is not None:
                self._identities[identity.id] = identity
            if personal is not None:
                self._put_tenant(personal[0].id, *personal)
            self._put_tenant(org_id, org, user, membership)

    def _require_tenant_free(
        self, org_id: UUID, org: Org, user: User, membership: Membership
    ) -> None:
        self._require_slug_free(org)
        self._require_live_identity_free(org_id, user)
        self._require_membership_free(org_id, membership)
        for table, entity in ((self._orgs, org), (self._users, user)):
            if entity.id in table:
                raise UniqueKeyTaken(f"{entity.id} is already written")
        if membership.id in self._memberships:
            raise UniqueKeyTaken(f"{membership.id} is already written")

    def _put_tenant(self, org_id: UUID, org: Org, user: User, membership: Membership) -> None:
        self._put(self._orgs, org_id, org)
        self._put(self._users, org_id, user)
        self._put(self._memberships, org_id, membership)

    async def create_member(
        self,
        org_id: UUID,
        user: User,
        membership: Membership,
        outbox_rows: tuple[OutboxRow, ...],
        identity: Identity | None = None,
        personal: tuple[Org, User, Membership] | None = None,
    ) -> None:
        async with self._lock:
            if identity is not None:
                self._require_email_free(identity)
            if personal is not None:
                self._require_tenant_free(personal[0].id, *personal)
            self._require_live_identity_free(org_id, user)
            self._require_membership_free(org_id, membership)
            if user.id in self._users or membership.id in self._memberships:
                raise UniqueKeyTaken(f"{user.id} or {membership.id} is already written")
            if identity is not None:
                self._identities[identity.id] = identity
            if personal is not None:
                self._put_tenant(personal[0].id, *personal)
            self._put(self._users, org_id, user, outbox_rows)
            self._put(self._memberships, org_id, membership)

    async def remove_member(
        self,
        org_id: UUID,
        user: User,
        membership: Membership,
        outbox_rows: tuple[OutboxRow, ...],
        revocation_row: Callable[[str, UUID], OutboxRow],
    ) -> tuple[OutboxRow, ...]:
        at, by = user.deleted_at, user.deleted_by
        if at is None or by is None:
            raise ValueError("remove_member lands a user that is deleted")
        # Every check, then every write: the twin of one commit.
        async with self._lock:
            if self._get(self._users, org_id, user.id) is None:
                raise NotFound(f"user {user.id} is not in {org_id}")
            if self._get(self._memberships, org_id, membership.id) is None:
                raise NotFound(f"membership {membership.id} is not in {org_id}")
            sessions = [
                s.model_copy(update={"revoked_at": at, "updated_at": at, "updated_by": by})
                for s in self._rows(self._sessions, org_id)
                if s.user_id == user.id and s.revoked_at is None
            ]
            keys = [
                k.model_copy(
                    update={"deleted_at": at, "deleted_by": by, "updated_at": at, "updated_by": by}
                )
                for k in self._rows(self._api_keys, org_id)
                if k.user_id == user.id and k.deleted_at is None
            ]
            revoked = tuple(
                [revocation_row("tenancy.session.revoked", s.id) for s in sessions]
                + [revocation_row("tenancy.api_key.deleted", k.id) for k in keys]
            )
            self._put(self._users, org_id, user, (*outbox_rows, *revoked))
            self._put(self._memberships, org_id, membership)
            for session in sessions:
                self._put(self._sessions, org_id, session)
            for key in keys:
                self._put(self._api_keys, org_id, key)
            return revoked

    async def read_users(self, org_id: UUID, after: UUID | None, limit: int) -> list[User]:
        live = [u for u in self._rows(self._users, org_id) if u.deleted_at is None]
        if after is not None:
            live = [u for u in live if is_after_in_id_order(u.id, after)]
        return live[:limit]

    async def read_user(self, org_id: UUID, user_id: UUID) -> User | None:
        return self._get(self._users, org_id, user_id)

    async def read_users_by_identity(
        self, identity_id: UUID, limit: int
    ) -> list[tuple[UUID, User]]:
        return [
            (org_id, user)
            for org_id, user in self._rows_across_tenants(self._users)
            if user.identity_id == identity_id and user.deleted_at is None
        ][:limit]

    async def read_memberships_by_identity(
        self, identity_id: UUID, limit: int, after_user_id: UUID | None = None
    ) -> list[OrgMembership]:
        found: list[OrgMembership] = []
        for org_id, user in self._rows_across_tenants(self._users):
            if user.identity_id != identity_id or user.deleted_at is not None:
                continue
            if after_user_id is not None and not is_after_in_id_order(user.id, after_user_id):
                continue
            org = self._get(self._orgs, org_id, org_id)
            membership = await self.read_membership_for_user(org_id, user.id)
            if org is None or org.deleted_at is not None or membership is None:
                continue
            found.append(OrgMembership(org=org, user=user, role=membership.role))
        return found[:limit]

    async def write_user(
        self, org_id: UUID, user: User, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        async with self._lock:
            self._require_live_identity_free(org_id, user)
            self._put(self._users, org_id, user, outbox_rows)

    def _require_live_identity_free(self, org_id: UUID, user: User) -> None:
        # uq_users_org_id_identity_id_live: one live user per identity in a tenant.
        if user.deleted_at is None:
            self._require_free(
                self._rows(self._users, org_id),
                user,
                lambda other: other.identity_id == user.identity_id and other.deleted_at is None,
                f"identity {user.identity_id} already has a live user in this org",
            )

    async def read_memberships(
        self, org_id: UUID, limit: int, after_user_id: UUID | None = None
    ) -> list[Membership]:
        live = [m for m in self._rows(self._memberships, org_id) if m.deleted_at is None]
        if after_user_id is not None:
            live = [m for m in live if is_after_in_id_order(m.user_id, after_user_id)]
        return sorted(live, key=lambda m: m.user_id)[:limit]

    async def read_membership_for_user(self, org_id: UUID, user_id: UUID) -> Membership | None:
        return next(
            (
                m
                for m in self._rows(self._memberships, org_id)
                if m.user_id == user_id and m.deleted_at is None
            ),
            None,
        )

    async def write_membership(
        self, org_id: UUID, membership: Membership, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        self._require_membership_free(org_id, membership)
        self._put(self._memberships, org_id, membership, outbox_rows)

    def _require_membership_free(self, org_id: UUID, membership: Membership) -> None:
        # uq_memberships_org_id_user_id: one live membership per user in a tenant;
        # an ended one frees the key.
        if membership.deleted_at is None:
            self._require_free(
                self._rows(self._memberships, org_id),
                membership,
                lambda other: other.user_id == membership.user_id and other.deleted_at is None,
                "uq_memberships_org_id_user_id",
            )

    async def read_sessions(
        self, org_id: UUID, user_id: UUID, live_at: datetime, limit: int
    ) -> list[Session]:
        live = [
            s
            for s in self._rows(self._sessions, org_id)
            if s.user_id == user_id and s.revoked_at is None and s.expires_at > live_at
        ]
        return live[::-1][:limit]

    async def read_session(self, org_id: UUID, session_id: UUID) -> Session | None:
        return self._get(self._sessions, org_id, session_id)

    async def read_session_by_digest(self, token_hash: str) -> tuple[UUID, Session] | None:
        return next(
            (
                (org_id, session)
                for org_id, session in self._sessions.values()
                if session.token_hash == token_hash
            ),
            None,
        )

    async def read_session_by_id(self, session_id: UUID) -> tuple[UUID, Session] | None:
        return self._sessions.get(session_id)

    async def touch_session(self, org_id: UUID, session_id: UUID, seen_at: datetime) -> None:
        async with self._lock:
            session = self._get(self._sessions, org_id, session_id)
            if session is not None and session.revoked_at is None:
                self._put(
                    self._sessions, org_id, session.model_copy(update={"last_seen_at": seen_at})
                )

    async def write_session(
        self, org_id: UUID, session: Session, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        self._require_free(
            self._every(self._sessions),
            session,
            lambda other: other.token_hash == session.token_hash,
            "uq_sessions_token_hash",
        )
        self._put(self._sessions, org_id, session, outbox_rows)

    async def replace_session(
        self,
        org_id: UUID,
        session: Session,
        ended_org_id: UUID,
        ended: Session,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        # Every check, then every write: the twin of one commit.
        async with self._lock:
            stored = self._get(self._sessions, ended_org_id, ended.id)
            if stored is None:
                raise NotFound(f"session {ended.id} is not in {ended_org_id}")
            if stored.revoked_at is not None:
                raise Conflict(f"session {ended.id} has already ended")
            if session.id in self._sessions:
                raise UniqueKeyTaken(f"session {session.id} is already written")
            self._require_free(
                self._every(self._sessions),
                session,
                lambda other: other.token_hash == session.token_hash,
                "uq_sessions_token_hash",
            )
            self._put(self._sessions, ended_org_id, ended, outbox_rows)
            self._put(self._sessions, org_id, session)

    async def read_api_keys(
        self, org_id: UUID, after: UUID | None, limit: int, user_id: UUID | None = None
    ) -> list[ApiKey]:
        live = [
            k
            for k in self._rows(self._api_keys, org_id)
            if k.deleted_at is None and (user_id is None or k.user_id == user_id)
        ]
        newest_first = live[::-1]
        if after is not None:
            newest_first = [k for k in newest_first if is_after_newest_first(k.id, after)]
        return newest_first[:limit]

    async def read_api_key(self, org_id: UUID, api_key_id: UUID) -> ApiKey | None:
        return self._get(self._api_keys, org_id, api_key_id)

    async def read_api_key_by_digest(self, key_hash: str) -> tuple[UUID, ApiKey] | None:
        return next(
            ((org_id, key) for org_id, key in self._api_keys.values() if key.key_hash == key_hash),
            None,
        )

    async def issue_api_key(
        self,
        org_id: UUID,
        api_key: ApiKey,
        outbox_rows: tuple[OutboxRow, ...],
        attempt_id: UUID | None,
    ) -> tuple[ApiKey, bool]:
        async with self._lock:
            self._require_key_hash_free(api_key)
            if self._insert(self._api_keys, org_id, api_key, outbox_rows):
                return api_key, True
            stored = self._get(self._api_keys, org_id, api_key.id)
            if (
                stored is None
                or stored.user_id != api_key.user_id
                or stored.deleted_at is not None
                or not self._attempt_holds(org_id, api_key.id, attempt_id)
            ):
                raise Conflict(f"api key {api_key.id} cannot be re-minted")
            reissued = stored.model_copy(
                update={
                    "key_hash": api_key.key_hash,
                    "updated_at": api_key.updated_at,
                    "updated_by": api_key.updated_by,
                }
            )
            self._put(self._api_keys, org_id, reissued)
            return reissued, False

    async def write_api_key(
        self, org_id: UUID, api_key: ApiKey, outbox_rows: tuple[OutboxRow, ...] = ()
    ) -> None:
        self._require_key_hash_free(api_key)
        self._put(self._api_keys, org_id, api_key, outbox_rows)

    def _attempt_holds(self, org_id: UUID, target_id: UUID, attempt_id: UUID | None) -> bool:
        """The twin of the marker read inside the Postgres statement's WHERE.
        No key means no marker and so no rerun to admit; a storage built with
        no markers to ask cannot fence the write and so never re-mints."""
        if attempt_id is None:
            return False
        if self._markers is None:
            raise RuntimeError("this memory storage was built without markers to fence on")
        return self._markers.holds(org_id, target_id, attempt_id)

    def _require_key_hash_free(self, api_key: ApiKey) -> None:
        self._require_free(
            self._every(self._api_keys),
            api_key,
            lambda other: other.key_hash == api_key.key_hash,
            "uq_api_keys_key_hash",
        )

    async def purge_deleted(self, org_id: UUID, before: datetime) -> int:
        gone_users = [
            u.id
            for u in self._rows(self._users, org_id)
            if u.deleted_at is not None and u.deleted_at < before
        ]
        gone_memberships = [
            m.id
            for m in self._rows(self._memberships, org_id)
            if m.user_id in gone_users or (m.deleted_at is not None and m.deleted_at < before)
        ]
        gone_keys = [
            k.id
            for k in self._rows(self._api_keys, org_id)
            if (k.deleted_at is not None and k.deleted_at < before) or k.expires_at < before
        ]
        gone_sessions = [
            s.id
            for s in self._rows(self._sessions, org_id)
            if (s.revoked_at is not None and s.revoked_at < before) or s.expires_at < before
        ]
        gone_tickets = [
            t.id
            for t in self._rows(self._socket_tickets, org_id)
            if (t.redeemed_at is not None and t.redeemed_at < before) or t.expires_at < before
        ]
        for table, ids in (
            (self._users, gone_users),
            (self._memberships, gone_memberships),
            (self._api_keys, gone_keys),
            (self._sessions, gone_sessions),
            (self._socket_tickets, gone_tickets),
        ):
            for row_id in ids:
                del table[row_id]
        return (
            len(gone_users)
            + len(gone_memberships)
            + len(gone_keys)
            + len(gone_sessions)
            + len(gone_tickets)
        )

    async def purge_tenant(self, org_id: UUID) -> int:
        return (
            self._drop_tenant(self._users, org_id)
            + self._drop_tenant(self._memberships, org_id)
            + self._drop_tenant(self._api_keys, org_id)
            + self._drop_tenant(self._sessions, org_id)
            + self._drop_tenant(self._socket_tickets, org_id)
        )

    @classmethod
    def _drop_tenant[E: HasId](cls, table: MemoryTable[E], org_id: UUID) -> int:
        gone = [row.id for row in cls._rows(table, org_id)]
        for row_id in gone:
            del table[row_id]
        return len(gone)

    async def write_socket_ticket(self, org_id: UUID, ticket: SocketTicket) -> None:
        self._require_free(
            self._every(self._socket_tickets),
            ticket,
            lambda other: other.ticket_hash == ticket.ticket_hash,
            "uq_socket_tickets_ticket_hash",
        )
        self._put(self._socket_tickets, org_id, ticket)

    async def redeem_socket_ticket(
        self, ticket_hash: str, redeemed_at: datetime
    ) -> tuple[UUID, SocketTicket] | None:
        async with self._lock:
            for org_id, ticket in self._socket_tickets.values():
                if ticket.ticket_hash == ticket_hash:
                    if ticket.redeemed_at is not None:
                        return None
                    consumed = ticket.model_copy(update={"redeemed_at": redeemed_at})
                    self._put(self._socket_tickets, org_id, consumed)
                    return org_id, consumed
            return None
