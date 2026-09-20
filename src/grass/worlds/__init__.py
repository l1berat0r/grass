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
    "load_world_package",
    "register_world_package_run",
]
