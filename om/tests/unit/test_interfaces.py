"""Every interface is abstract, checked rather than written down: a class
named `*Interface` under the object model or the infrastructure toolkit is an
`ABC`, and every public method it declares is abstract, so an impl that
forgets one is refused when it is built, not when the method is first
called and returns None."""

import importlib
import inspect
import pkgutil
from abc import ABC
from collections.abc import Iterator
from types import ModuleType

import pytest

import tadas.infra
import tadas.om


def interfaces(package: ModuleType) -> Iterator[type]:
    for module_info in pkgutil.walk_packages(package.__path__, prefix=f"{package.__name__}."):
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and name.endswith("Interface")
                and obj.__module__ == module.__name__
            ):
                yield obj


INTERFACES = sorted(
    {*interfaces(tadas.om), *interfaces(tadas.infra)}, key=lambda cls: cls.__qualname__
)


def public_methods(interface: type) -> list[str]:
    return [
        name
        for name, member in vars(interface).items()
        if not name.startswith("_") and inspect.isfunction(member)
    ]


def test_the_scan_finds_the_roots() -> None:
    names = {cls.__name__ for cls in INTERFACES}
    assert {"StorageInterface", "InfraInterface", "TenancyManagerInterface"} <= names


@pytest.mark.parametrize("interface", INTERFACES, ids=lambda cls: cls.__name__)
def test_every_interface_is_an_abc_with_abstract_methods(interface: type) -> None:
    assert issubclass(interface, ABC), f"{interface.__name__} is not an ABC"
    methods = public_methods(interface)
    assert methods, f"{interface.__name__} declares no method"
    concrete = [
        name
        for name in methods
        if not getattr(vars(interface)[name], "__isabstractmethod__", False)
    ]
    assert not concrete, f"{interface.__name__} has concrete methods: {concrete}"
