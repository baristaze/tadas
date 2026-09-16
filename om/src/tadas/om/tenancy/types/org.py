from tadas.om.base import Identifiable, Named, SoftDeletable, Trackable


class Org(Identifiable, Named, Trackable, SoftDeletable):
    slug: str
