# SPDX-License-Identifier: GPL-3.0-only

import ast
import tomllib
from pathlib import Path

import grass
import grass.core
import grass.worlds


def test_core_package_imports_without_application_frameworks() -> None:
    assert grass.__doc__ == "GRASS simulation core."
    assert grass.core.LogicalTime(0).nanoseconds_from_origin == 0
    assert grass.core.GEL_LANGUAGE_VERSION == 1
    assert grass.core.WORLD_DEFINITION_SCHEMA_VERSION == 1
    assert grass.worlds.WORLD_PACKAGE_VERSION == 1


def test_slice_14_adds_no_mandatory_dependency() -> None:
    with Path("pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["dependencies"] == []


def test_inner_architecture_packages_do_not_import_cli_workspace_contracts() -> None:
    violations: list[str] = []
    root = Path("src/grass")
    for package_name in ("core", "application", "runtime", "worlds"):
        for path in (root / package_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(
                        alias.name == "grass.cli" or alias.name.startswith("grass.cli.")
                        for alias in node.names
                    ):
                        violations.append(f"{path}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    module = "" if node.module is None else node.module
                    if (
                        node.level == 0
                        and (module == "grass.cli" or module.startswith("grass.cli."))
                    ) or (node.level > 0 and (module == "cli" or module.startswith("cli."))):
                        violations.append(f"{path}:{node.lineno}")

    assert violations == []
