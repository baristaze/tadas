from tadas.om.base import Identifiable, Trackable


class Identity(Identifiable, Trackable):
    """A person, across every tenant. Global by nature: a user is this identity inside one org."""

    email: str
    password_hash: str
    is_operator: bool = False
