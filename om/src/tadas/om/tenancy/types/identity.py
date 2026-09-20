from tadas.om.base import Identifiable, Trackable
from tadas.om.opcontext import OperatorRole


class Identity(Identifiable, Trackable):
    """A person, across every tenant. Global by nature: a user is this identity inside one org."""

    email: str
    password_hash: str
    # The operator allowlist is this field: a person whose entry is set may be
    # admitted to the operator plane, and the entry says what they may do there.
    operator_role: OperatorRole | None = None
