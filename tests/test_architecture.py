"""Import rules that keep the evals a consumer of the app, and adapters behind bootstrap.

The rules read import statements, absolute and relative. An import by name at run time, such as
importlib.import_module, is not seen.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "resourcly"
MODULES = sorted(PACKAGE.rglob("*.py"))


def module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports_in(source: str, module: str, is_package: bool) -> set[str]:
    """The resourcly modules and names a module's source imports, relative ones resolved."""
    package = module.split(".") if is_package else module.split(".")[:-1]
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            name = ".".join([*base, *([node.module] if node.module else [])])
            found |= {name, *(f"{name}.{alias.name}" for alias in node.names)}
    return {name for name in found if name.split(".")[0] == "resourcly"}


def imports(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    return imports_in(source, module_name(path), is_package=path.name == "__init__.py")


def inside(name: str, package: str) -> bool:
    return name == package or name.startswith(f"{package}.")


EVALS = [path for path in MODULES if inside(module_name(path), "resourcly.eval_harness")]
APP = [path for path in MODULES if path not in EVALS]
NOT_BOOTSTRAP = [
    path
    for path in MODULES
    if module_name(path) != "resourcly.bootstrap"
    and not inside(module_name(path), "resourcly.adapters")
]


@pytest.mark.parametrize("path", EVALS, ids=module_name)
def test_evals_reach_the_app_only_through_bootstrap_and_ports(path: Path) -> None:
    allowed = ("resourcly.bootstrap", "resourcly.ports", "resourcly.eval_harness")
    imported = imports(path) - {"resourcly"}

    assert [name for name in imported if not any(inside(name, a) for a in allowed)] == []


@pytest.mark.parametrize("path", APP, ids=module_name)
def test_the_app_never_imports_the_evals(path: Path) -> None:
    assert [name for name in imports(path) if inside(name, "resourcly.eval_harness")] == []


@pytest.mark.parametrize("path", NOT_BOOTSTRAP, ids=module_name)
def test_only_bootstrap_builds_adapters(path: Path) -> None:
    assert [name for name in imports(path) if inside(name, "resourcly.adapters")] == []


def test_relative_imports_are_resolved_against_the_module() -> None:
    source = "from ..services import GoldService\nfrom . import metrics\nfrom .cases import Case\n"

    found = imports_in(source, "resourcly.eval_harness.harness", is_package=False)

    assert found == {
        "resourcly.services",
        "resourcly.services.GoldService",
        "resourcly.eval_harness",
        "resourcly.eval_harness.metrics",
        "resourcly.eval_harness.cases",
        "resourcly.eval_harness.cases.Case",
    }
    assert imports_in("from .adapters import x", "resourcly", is_package=True) == {
        "resourcly.adapters",
        "resourcly.adapters.x",
    }
