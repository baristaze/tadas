"""The platform's size, what the first responder to an alarm reads before it
escalates: an alarm on a platform of one tenant and one user is the
developer at work."""

from datetime import datetime

from tadas.om.base import Platform


class PlatformSize(Platform):
    tenants: int  # live orgs
    users: int  # live users across every tenant; a person in two orgs counts twice
    tasks_last_24h: int  # tasks created in the window, whatever became of them since
    events_last_24h: int  # events produced in the window, every tenant's stream
    since: datetime  # where the window starts; it ends at the read
