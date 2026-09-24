# SPDX-License-Identifier: GPL-3.0-only

"""Data-defined WorldPackage loading, snapshots, and runtime composition."""

from grass.worlds.composition import (
    OccurrenceRuntimeComposer,
    WorldCompositionError,
    compose_occurrence_engine,
)
from grass.worlds.mechanics import (
    DataDefinedScenarioOccurrenceResolver,
    WorldMechanicExecutionError,
)
from grass.worlds.package import (
    WORLD_PACKAGE_MANIFEST,
    WORLD_PACKAGE_VERSION,
    UnsupportedWorldPackageVersionError,
    WorldPackage,
    WorldPackageError,
    WorldPackageFormatError,
    WorldPackageManifest,
    WorldPackageMaterialError,
    WorldPackagePathError,
    WorldPackageValidationError,
    load_world_package,
)
from grass.worlds.snapshots import (
    FilesystemWorldSnapshotStore,
    WorldPackageSnapshot,
    WorldSnapshotConflictError,
    WorldSnapshotError,
    WorldSnapshotIntegrityError,
    WorldSnapshotNotFoundError,
    WorldSnapshotPathError,
    register_world_package_run,
)
from grass.worlds.templates import (
    WorldTemplateDestinationError,
    WorldTemplateDestinationExistsError,
    WorldTemplateError,
    WorldTemplateInfo,
    WorldTemplateIntegrityError,
    WorldTemplateNotFoundError,
    get_world_template,
    initialize_world_template,
    list_world_templates,
)

__all__ = [
    "DataDefinedScenarioOccurrenceResolver",
    "FilesystemWorldSnapshotStore",
    "OccurrenceRuntimeComposer",
    "UnsupportedWorldPackageVersionError",
    "WORLD_PACKAGE_MANIFEST",
    "WORLD_PACKAGE_VERSION",
    "WorldCompositionError",
    "WorldMechanicExecutionError",
    "WorldPackage",
    "WorldPackageError",
    "WorldPackageFormatError",
    "WorldPackageManifest",
    "WorldPackageMaterialError",
    "WorldPackagePathError",
    "WorldPackageValidationError",
    "WorldPackageSnapshot",
    "WorldSnapshotError",
    "WorldSnapshotConflictError",
    "WorldSnapshotIntegrityError",
    "WorldSnapshotNotFoundError",
    "WorldSnapshotPathError",
    "compose_occurrence_engine",
    "get_world_template",
    "initialize_world_template",
    "list_world_templates",
    "load_world_package",
    "register_world_package_run",
    "WorldTemplateDestinationError",
    "WorldTemplateDestinationExistsError",
    "WorldTemplateError",
    "WorldTemplateInfo",
    "WorldTemplateIntegrityError",
    "WorldTemplateNotFoundError",
]
