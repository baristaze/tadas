"""Import direction, checked rather than written down: no module of the
object model reaches past an infra interface to an impl. A static scan of
the source files; nothing here imports the modules it inspects.

That the object model and infra import no service or worker, and that
infra imports nothing from the object model, is `make arch-check` (CON-12
and CON-10). What stays here is what the checker does not decide: an infra
module that is not a capability's interface package, such as
`tadas.infra.aws_clients` or `tadas.infra.breaker`, is an impl too."""

import ast
import importlib.util
from collections.abc import Iterator
from pathlib import Path

import pytest

INFRA_INTERFACE_MODULES = frozenset(
    {
        "tadas.infra",
        "tadas.infra.root",
        "tadas.infra.base",
        "tadas.infra.exceptions",
        "tadas.infra.observability",
        "tadas.infra.trust",
        "tadas.infra.cache",
        "tadas.infra.buckets",
        "tadas.infra.topics",
        "tadas.infra.queues",
        "tadas.infra.secrets",
    }
)
"""A capability's interface is its package; every module beneath it, and
everything under `tadas.infra.impl`, is an impl."""


def package_root(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    assert spec is not None and spec.submodule_search_locations, name
    return Path(next(iter(spec.submodule_search_locations)))


def modules_under(package: str) -> Iterator[tuple[str, Path]]:
    root = package_root(package)
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).with_suffix("")
        parts = [package, *relative.parts]
        if parts[-1] == "__init__":
            parts.pop()
        yield ".".join(parts), path


def imported_modules(module: str, path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.rsplit(".", node.level)[0]
                yield f"{base}.{node.module}" if node.module else base
            elif node.module:
                yield node.module


def is_under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def is_infra_impl(name: str) -> bool:
    return is_under(name, "tadas.infra") and name not in INFRA_INTERFACE_MODULES


OM_MODULES = list(modules_under("tadas.om"))


@pytest.mark.parametrize("module,path", OM_MODULES, ids=[m for m, _ in OM_MODULES])
def test_om_reaches_infra_only_through_interfaces(module: str, path: Path) -> None:
    """Managers receive infra handles through their constructors; the impl
    behind a handle is chosen by the app container. `tadas.om.root` builds the
    managers and is the one module allowed to name what it is handed."""
    if module == "tadas.om.root":
        return
    offending = [name for name in imported_modules(module, path) if is_infra_impl(name)]
    assert offending == [], f"{module} imports infra impls {offending}"


def test_the_scan_sees_the_whole_tree() -> None:
    names = {m for m, _ in OM_MODULES}
    assert {"tadas.om.root", "tadas.om.base", "tadas.om.tasks.impl.manager"} <= names
    assert is_infra_impl("tadas.infra.cache.valkey")
    assert is_infra_impl("tadas.infra.impl.local")
    assert is_infra_impl("tadas.infra.topics.dispatch")
    assert not is_infra_impl("tadas.infra.topics")
