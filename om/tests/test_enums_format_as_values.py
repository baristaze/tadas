"""Every enum the platform formats into a key, a name, a log line, or a
message formats as its value. A `(str, Enum)` member formats as `Class.MEMBER`
on Python 3.12 and later, so an f-string built from one names the class
instead of the value; every one of them is a `StrEnum`."""

import enum

import pytest

from tadas.infra.buckets import Buckets
from tadas.infra.cache import CacheScope
from tadas.infra.queues import Queues
from tadas.infra.topics import Topics
from tadas.om.opcontext import (
    AppType,
    CredentialKind,
    OperatorPermission,
    OperatorRole,
    Permission,
    Role,
)
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.scopes import ScopeKind
from tadas.om.tasks.types.task import TaskScope, TaskStatus
from tadas.om.work.types.work_item import WorkKind, WorkStatus

ENUMS = [
    Buckets,
    CacheScope,
    Queues,
    Topics,
    AppType,
    CredentialKind,
    OperatorPermission,
    OperatorRole,
    Permission,
    Role,
    DatabaseRole,
    ScopeKind,
    TaskScope,
    TaskStatus,
    WorkKind,
    WorkStatus,
]


@pytest.mark.parametrize("kind", ENUMS, ids=lambda kind: kind.__name__)
def test_a_member_formats_as_its_value(kind: type[enum.Enum]) -> None:
    assert issubclass(kind, enum.StrEnum)
    for member in kind:
        assert f"{member}" == member.value
        assert str(member) == member.value
