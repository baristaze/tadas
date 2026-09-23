from enum import StrEnum
from uuid import UUID

from pydantic import model_validator

from tadas.om.base import Identifiable, Named, SoftDeletable, Trackable


class OrgKind(StrEnum):
    """What an org is for. Every person has exactly one personal org, made
    with them; every other org is a team org, made on purpose."""

    PERSONAL = "personal"
    TEAM = "team"


class Org(Identifiable, Named, Trackable, SoftDeletable):
    slug: str
    kind: OrgKind = OrgKind.TEAM
    personal_identity_id: UUID | None = None
    """The person a personal org belongs to; None on a team org. One living
    personal org per identity, which the database holds."""

    @model_validator(mode="after")
    def _personal_names_its_person(self) -> Org:
        if (self.kind is OrgKind.PERSONAL) != (self.personal_identity_id is not None):
            raise ValueError("a personal org names its person, and a team org names none")
        return self

    @property
    def personal(self) -> bool:
        return self.kind is OrgKind.PERSONAL
