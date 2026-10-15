"""The one client of the Tadas API: the transport, and each namespace's calls
composed onto it. Every operation is a method that returns a typed view; the
methods of one namespace live in its module under `calls/`, so a change to
one namespace's calls touches that module alone."""

from tadas.client.calls.change_events import ChangeEventsCalls
from tadas.client.calls.leases import LeasesCalls
from tadas.client.calls.media import MediaCalls
from tadas.client.calls.tasks import TasksCalls
from tadas.client.calls.tenancy import TenancyCalls
from tadas.client.calls.work import WorkCalls


# TasksCalls builds on MediaCalls' upload, so it comes before it.
class ApiClient(TasksCalls, ChangeEventsCalls, LeasesCalls, MediaCalls, TenancyCalls, WorkCalls):
    """Async. `token` is the bearer every request carries; an operation that
    needs another credential (the sign-in flow) takes it as an argument."""
