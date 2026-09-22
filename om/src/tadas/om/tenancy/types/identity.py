from datetime import datetime

from tadas.om.base import Identifiable, Trackable
from tadas.om.opcontext import OperatorRole


class Identity(Identifiable, Trackable):
    """A person, across every tenant. Global by nature: a user is this identity inside one org."""

    email: str
    password_hash: str
    # The operator allowlist is this field: a person whose entry is set may be
    # admitted to the operator plane, and the entry says what they may do there.
    operator_role: OperatorRole | None = None
    # The run of failed sign-ins since the last one that succeeded, and when
    # the last of them was: the sign-in delay grows from these. They live in
    # the tenancy role's own storage, so the delay holds when the cache that
    # counts per address is down.
    failed_sign_ins: int = 0
    last_failed_sign_in_at: datetime | None = None
