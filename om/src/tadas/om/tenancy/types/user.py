from uuid import UUID

from tadas.om.base import Identifiable, SoftDeletable, Trackable


class User(Identifiable, Trackable, SoftDeletable):
    identity_id: UUID
    email: str
    display_name: str
