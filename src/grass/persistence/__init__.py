# SPDX-License-Identifier: GPL-3.0-only

"""Durable local persistence contracts and implementations."""

from grass.persistence.contracts import (
    PersistenceError,
    PersistenceIntegrityError,
    RunConfigSnapshotRepository,
    RunEventStoreRepository,
    RunId,
    RunNotFoundError,
    RunRepository,
    SimulationRunRecord,
    UnsupportedStorageVersionError,
    WorldDefinitionSnapshotRepository,
    WorldMaterialKind,
)
from grass.persistence.sqlite import (
    SQLITE_STORAGE_SCHEMA_VERSION,
    SqliteEventStore,
    SqlitePersistence,
)

__all__ = [
    "PersistenceError",
    "PersistenceIntegrityError",
    "RunConfigSnapshotRepository",
    "RunEventStoreRepository",
    "RunId",
    "RunNotFoundError",
    "RunRepository",
    "SimulationRunRecord",
    "SQLITE_STORAGE_SCHEMA_VERSION",
    "SqliteEventStore",
    "SqlitePersistence",
    "UnsupportedStorageVersionError",
    "WorldDefinitionSnapshotRepository",
    "WorldMaterialKind",
]
