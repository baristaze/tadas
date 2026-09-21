from uuid import UUID

from tadas.om.base import Identifiable, SoftDeletable, Trackable

PERSONAL_FIELDS = frozenset({"email", "display_name"})
"""The fields that say who a person is. The user row holds them and the purge
that erases a person removes them; the event stream, which outlives a removed
member, never carries them."""


class User(Identifiable, Trackable, SoftDeletable):
    identity_id: UUID
    email: str
    display_name: str
