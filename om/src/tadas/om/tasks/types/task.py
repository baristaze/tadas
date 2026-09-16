from tadas.om.base import Identifiable, SoftDeletable, Trackable


class Task(Identifiable, Trackable, SoftDeletable):
    title: str
    notes: str
    status: str
