"""Every storage method takes org_id first, except the enumerated exceptions,
each documented in place. Every manager method takes a context stage first;
the transitions take the weakest stage and are named here, so a new
principal-less method must be listed to pass.

These are signature tests. They read parameter names and annotations and
nothing else, so what they prove is that the tenant is offered to the query,
never that the query uses it: a method could take `org_id` and write a `WHERE`
without it and pass here. The fence is the predicate in the query, and its
evidence is the cross-tenant cases of the contract suites, each of which
presents another tenant's identifier and asserts that nothing is found and
nothing changes. `test_every_tenant_method_is_named_in_a_cross_tenant_case`
below holds the two halves to each other: it is the guard against a new
storage method arriving with no case, and it too reads names and not queries,
so a name listed with no case behind it passes. What the cases catch when a
predicate is taken out is recorded in `docs/runbooks/tenant-isolation.md`.
"""

import importlib
import inspect
import pkgutil

from contracts import (
    event_storage,
    idempotency_storage,
    outbox_storage,
    task_storage,
    tenancy_storage,
    work_storage,
)

import tadas.om
from tadas.om.opcontext import IdentityContext, OpContext, OperatorContext, RequestContext

STORAGE_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("TenancyStorageInterface", "read_identity"),
        ("TenancyStorageInterface", "read_identity_by_email"),
        ("TenancyStorageInterface", "write_identity"),
        ("TenancyStorageInterface", "record_failed_sign_in"),
        ("TenancyStorageInterface", "clear_failed_sign_ins"),
        ("TenancyStorageInterface", "read_org_by_slug"),
        ("TenancyStorageInterface", "read_orgs"),
        ("TenancyStorageInterface", "count_orgs"),
        ("TenancyStorageInterface", "count_users"),
        ("TasksStorageInterface", "count_created_since"),
        ("EventStorageInterface", "count_since"),
        ("TenancyStorageInterface", "read_users_by_identity"),
        ("TenancyStorageInterface", "read_memberships_by_identity"),
        ("TenancyStorageInterface", "read_session_by_id"),
        ("TenancyStorageInterface", "read_session_by_token_hash"),
        ("TenancyStorageInterface", "read_api_key_by_hash"),
        ("TenancyStorageInterface", "consume_socket_ticket"),
        ("WorkStorageInterface", "claim_next"),
        ("WorkStorageInterface", "purge_items"),
        ("OutboxStorageInterface", "claim_pending"),
        ("OutboxStorageInterface", "purge_done"),
    }
)

CROSS_TENANT_CASES: dict[str, frozenset[str]] = {
    "EventStorageInterface": event_storage.CROSS_TENANT_CASES,
    "IdempotencyStorageInterface": idempotency_storage.CROSS_TENANT_CASES,
    "OutboxStorageInterface": outbox_storage.CROSS_TENANT_CASES,
    "TasksStorageInterface": task_storage.CROSS_TENANT_CASES,
    "TenancyStorageInterface": tenancy_storage.CROSS_TENANT_CASES,
    "WorkStorageInterface": work_storage.CROSS_TENANT_CASES,
}
"""Which contract suite carries the cross-tenant cases of each storage
interface. A namespace whose suite is not here has no evidence behind its
fence, so the mapping is checked against the interfaces themselves."""

MANAGER_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # The outbox relay is the documented exception: it runs after a core write
        # or in the sweep, under the tenant the row names, and takes no stage.
        ("OutboxRelayInterface", "relay"),
        ("OutboxRelayInterface", "relay_pending"),
        ("OutboxRelayInterface", "purge_done"),
        # And the enqueue the relay makes: it runs on the relay's side of the
        # handoff, under the tenant the row names, and stamps the actor from it.
        ("WorkManagerInterface", "enqueue_relayed"),
        # The queue's purge, like the outbox's: one sweep step across tenants.
        ("WorkManagerInterface", "purge_items"),
    }
)

STAGES: tuple[type, ...] = (RequestContext, IdentityContext, OpContext, OperatorContext)

REQUEST_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Take `RequestContext`, the weakest stage: nobody is known yet.
        ("TenancyManagerInterface", "bootstrap"),
        ("TenancyManagerInterface", "add_member"),
        ("TenancyManagerInterface", "sign_up"),
        ("TenancyManagerInterface", "login"),
        ("TenancyManagerInterface", "authenticate_login"),
        ("TenancyManagerInterface", "authenticate"),
        ("TenancyManagerInterface", "resume"),
        ("TenancyManagerInterface", "redeem_ticket"),
        ("TenancyManagerInterface", "service_context"),
        ("TenancyManagerInterface", "service_contexts"),
        ("WorkManagerInterface", "claim"),
        ("WorkManagerInterface", "maintenance_contexts"),
    }
)

IDENTITY_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Take `IdentityContext`: a person is verified, no tenant is chosen.
        ("TenancyManagerInterface", "exchange_login"),
        ("TenancyManagerInterface", "get_identity_memberships"),
        ("TenancyManagerInterface", "admit_operator"),
    }
)


def interfaces(*suffixes: str) -> list[type]:
    found: list[type] = []
    for module_info in pkgutil.walk_packages(tadas.om.__path__, prefix="tadas.om."):
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and name.endswith(suffixes)
                and obj.__module__ == module.__name__
                and name not in suffixes
            ):
                found.append(obj)
    return found


def operations(interface: type) -> list[tuple[str, list[inspect.Parameter]]]:
    result: list[tuple[str, list[inspect.Parameter]]] = []
    for name, member in inspect.getmembers(interface, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        params = list(inspect.signature(member).parameters.values())[1:]
        result.append((name, params))
    return result


def stage_of(param: inspect.Parameter) -> type | None:
    """The stage a first parameter is annotated with, by class or by name (a
    module under `from __future__ import annotations` leaves a string)."""
    annotation = param.annotation
    for stage in STAGES:
        if annotation is stage or annotation == stage.__name__:
            return stage
    return None


def test_storage_methods_take_org_id_first_except_the_documented_ones() -> None:
    seen: set[tuple[str, str]] = set()
    for interface in interfaces("StorageInterface"):
        for name, params in operations(interface):
            key = (interface.__name__, name)
            if [p.name for p in params[:1]] == ["org_id"]:
                assert key not in STORAGE_EXCEPTIONS, f"{key} is listed but takes org_id"
                continue
            seen.add(key)
            assert key in STORAGE_EXCEPTIONS, f"{key} does not take org_id first"
            doc = getattr(interface, name).__doc__ or ""
            assert doc.startswith(("Global", "Cross-tenant")), f"{key} lacks its reason"
    assert seen == STORAGE_EXCEPTIONS, f"stale entries: {STORAGE_EXCEPTIONS - seen}"


def test_every_tenant_method_is_named_in_a_cross_tenant_case() -> None:
    """The other half of the rule above. A method that takes `org_id` has a
    contract case presenting another tenant's, so the fence is proven by a
    query that runs and not by a parameter that exists. This reads the names
    the suites declare, so it catches a method that arrives with no case; that
    the named case does what it says is the suites' own business, and what
    happens when a predicate goes is the negative control's."""
    declared = {name for cases in CROSS_TENANT_CASES.values() for name in cases}
    found = {interface.__name__ for interface in interfaces("StorageInterface")}
    assert set(CROSS_TENANT_CASES) == found, "a storage interface with no contract suite named"
    for interface in interfaces("StorageInterface"):
        cases = CROSS_TENANT_CASES[interface.__name__]
        for name, params in operations(interface):
            takes_tenant = [p.name for p in params[:1]] == ["org_id"]
            if takes_tenant:
                assert name in cases, f"({interface.__name__}, {name}) has no cross-tenant case"
            else:
                assert name not in cases, f"({interface.__name__}, {name}) takes no tenant"
        stale = cases - {name for name, _ in operations(interface)}
        assert not stale, f"{interface.__name__} names cases for gone methods: {sorted(stale)}"
    assert declared, "the suites declare no cross-tenant cases at all"


def test_manager_methods_take_a_stage_first_except_the_documented_ones() -> None:
    seen: set[tuple[str, str]] = set()
    for interface in interfaces("ManagerInterface", "RelayInterface"):
        for name, params in operations(interface):
            key = (interface.__name__, name)
            if params and stage_of(params[0]) is not None:
                assert key not in MANAGER_EXCEPTIONS, f"{key} is listed but takes a stage"
                continue
            seen.add(key)
            assert key in MANAGER_EXCEPTIONS, f"{key} takes no context stage first"
            doc = getattr(interface, name).__doc__ or ""
            assert "Platform-internal" in doc or name == "relay", f"{key} lacks its reason"
    assert seen == MANAGER_EXCEPTIONS, f"stale entries: {MANAGER_EXCEPTIONS - seen}"


def test_the_transitions_are_the_only_methods_below_the_tenant_stage() -> None:
    """A method that takes `RequestContext` or `IdentityContext` produces a
    stronger stage; it must be named above, with its reason in the docstring."""
    by_request: set[tuple[str, str]] = set()
    by_identity: set[tuple[str, str]] = set()
    for interface in interfaces("ManagerInterface"):
        for name, params in operations(interface):
            key = (interface.__name__, name)
            stage = stage_of(params[0]) if params else None
            if stage is RequestContext:
                by_request.add(key)
            elif stage is IdentityContext:
                by_identity.add(key)
            else:
                continue
            doc = getattr(interface, name).__doc__ or ""
            assert doc.startswith("Platform-internal"), f"{key} lacks its reason"
    assert by_request == REQUEST_TRANSITIONS
    assert by_identity == IDENTITY_TRANSITIONS
