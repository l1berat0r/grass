# SPDX-License-Identifier: GPL-3.0-only

import tomllib
from pathlib import Path

import grass
import grass.core
import grass.worlds


def test_core_package_imports_without_application_frameworks() -> None:
    assert grass.__doc__ == "GRASS simulation core."
    assert grass.core.LogicalTime(0).nanoseconds_from_origin == 0
    assert grass.core.GEL_LANGUAGE_VERSION == 1
    assert grass.core.WORLD_DEFINITION_SCHEMA_VERSION == 3
    assert grass.worlds.WORLD_PACKAGE_VERSION == 1


def test_slice_14_adds_no_mandatory_dependency() -> None:
    with Path("pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["dependencies"] == []
