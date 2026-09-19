"""Every storage method takes org_id first, except the enumerated exceptions,
each documented in place. Every manager method takes a context stage first;
the transitions take the weakest stage and are named here, so a new
principal-less method must be listed to pass."""

import importlib
import inspect
import pkgutil

import tadas.om
from tadas.om.opcontext import AdminContext, IdentityContext, OpContext, RequestContext

STORAGE_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("TenancyStorageInterface", "read_identity"),
        ("TenancyStorageInterface", "read_identity_by_email"),
        ("TenancyStorageInterface", "write_identity"),
        ("TenancyStorageInterface", "read_org_by_slug"),
        ("TenancyStorageInterface", "read_orgs"),
        ("TenancyStorageInterface", "read_users_by_identity"),
        ("TenancyStorageInterface", "read_session_by_token_hash"),
        ("TenancyStorageInterface", "read_api_key_by_hash"),
        ("TenancyStorageInterface", "consume_socket_ticket"),
        ("WorkStorageInterface", "claim_next"),
        ("OutboxStorageInterface", "read_pending"),
        ("OutboxStorageInterface", "purge_done"),
    }
)

MANAGER_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # The outbox relay is the documented exception: it runs after a core write
        # or in the sweep, under the tenant the row names, and takes no stage.
        ("OutboxRelayInterface", "relay"),
        ("OutboxRelayInterface", "relay_pending"),
        ("OutboxRelayInterface", "purge_done"),
    }
)

STAGES: tuple[type, ...] = (RequestContext, IdentityContext, OpContext, AdminContext)

REQUEST_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Take `RequestContext`, the weakest stage: nobody is known yet.
        ("TenancyManagerInterface", "bootstrap"),
        ("TenancyManagerInterface", "add_member"),
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
