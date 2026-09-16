"""Every storage method takes org_id first and every manager method takes
ctx first, except the enumerated exceptions, each documented in place."""

import importlib
import inspect
import pkgutil

import tadas.om

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
        ("WorkStorageInterface", "claim_next"),
    }
)

MANAGER_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("TenancyManagerInterface", "bootstrap"),
        ("TenancyManagerInterface", "login"),
        ("TenancyManagerInterface", "exchange_login"),
        ("TenancyManagerInterface", "authenticate"),
        ("TenancyManagerInterface", "authenticate_operator"),
        ("TenancyManagerInterface", "resume"),
        ("TenancyManagerInterface", "redeem_ticket"),
        ("TenancyManagerInterface", "service_context"),
        ("TenancyManagerInterface", "service_contexts"),
        ("WorkManagerInterface", "claim"),
        ("WorkManagerInterface", "maintenance_contexts"),
    }
)


def interfaces(suffix: str) -> list[type]:
    found: list[type] = []
    for module_info in pkgutil.walk_packages(tadas.om.__path__, prefix="tadas.om."):
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and name.endswith(suffix)
                and obj.__module__ == module.__name__
                and name != suffix
            ):
                found.append(obj)
    return found


def operations(interface: type) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    for name, member in inspect.getmembers(interface, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        params = list(inspect.signature(member).parameters)[1:]
        result.append((name, params))
    return result


def test_storage_methods_take_org_id_first_except_the_documented_ones() -> None:
    seen: set[tuple[str, str]] = set()
    for interface in interfaces("StorageInterface"):
        for name, params in operations(interface):
            key = (interface.__name__, name)
            if params[:1] == ["org_id"]:
                assert key not in STORAGE_EXCEPTIONS, f"{key} is listed but takes org_id"
                continue
            seen.add(key)
            assert key in STORAGE_EXCEPTIONS, f"{key} does not take org_id first"
            doc = getattr(interface, name).__doc__ or ""
            assert doc.startswith(("Global", "Cross-tenant")), f"{key} lacks its reason"
    assert seen == STORAGE_EXCEPTIONS, f"stale entries: {STORAGE_EXCEPTIONS - seen}"


def test_manager_methods_take_a_context_first_except_the_documented_ones() -> None:
    seen: set[tuple[str, str]] = set()
    for interface in interfaces("ManagerInterface"):
        for name, params in operations(interface):
            key = (interface.__name__, name)
            if params[:1] in (["ctx"], ["admin"]):
                assert key not in MANAGER_EXCEPTIONS
                continue
            seen.add(key)
            assert key in MANAGER_EXCEPTIONS, f"{key} takes neither ctx nor admin first"
            doc = getattr(interface, name).__doc__ or ""
            assert doc.startswith("Platform-internal"), f"{key} lacks its reason"
    assert seen == MANAGER_EXCEPTIONS, f"stale entries: {MANAGER_EXCEPTIONS - seen}"
