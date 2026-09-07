# SPDX-License-Identifier: GPL-3.0-only

import grass
import grass.core


def test_core_package_imports_without_application_frameworks() -> None:
    assert grass.__doc__ == "GRASS simulation core."
    assert grass.core.LogicalTime(0).nanoseconds_from_origin == 0
    assert grass.core.WORLD_DEFINITION_SCHEMA_VERSION == 1
