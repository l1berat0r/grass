# SPDX-License-Identifier: GPL-3.0-only

"""Canonical loading and validation of one run's immutable world material."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from grass.core.event_store import EventStore
from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.persistence.contracts import RunId, SimulationRunRecord, WorldMaterialKind
from grass.worlds.snapshots import FilesystemWorldSnapshotStore, WorldPackageSnapshot


class LocalSimulationStorage(Protocol):
    def register_run(
        self,
        record: SimulationRunRecord,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None: ...

    def read_run(self, run_id: RunId, /) -> SimulationRunRecord: ...

    def list_runs(self) -> Sequence[SimulationRunRecord]: ...

    def read_world_definition(self, run_id: RunId, /) -> WorldDefinition: ...

    def read_run_config(self, run_id: RunId, /) -> SimulationRunConfig: ...

    def event_store(self, run_id: RunId, /) -> EventStore: ...


@dataclass(frozen=True, slots=True)
class LoadedRunMaterial:
    record: SimulationRunRecord
    definition: WorldDefinition
    config: SimulationRunConfig
    snapshot: WorldPackageSnapshot | None = None


def load_run_material(
    storage: LocalSimulationStorage,
    snapshot_store: FilesystemWorldSnapshotStore,
    run_id: RunId,
    /,
) -> LoadedRunMaterial:
    """Load canonical material according only to the persisted material discriminator."""

    if type(run_id) is not RunId:
        raise TypeError("run_id must be a RunId")
    record = storage.read_run(run_id)
    definition = storage.read_world_definition(run_id)
    config = storage.read_run_config(run_id)
    if record.run_id != run_id:
        raise ValueError("run repository returned a different RunId")
    if record.world_definition_ref != definition.ref:
        raise ValueError("run record does not reference its WorldDefinition")
    if config.world_definition_ref != definition.ref:
        raise ValueError("run config does not reference its WorldDefinition")
    if record.world_material_kind is WorldMaterialKind.PACKAGE_SNAPSHOT:
        snapshot = snapshot_store.load(run_id, definition)
        return LoadedRunMaterial(record, definition, config, snapshot)
    if record.world_material_kind is WorldMaterialKind.DEFINITION_ONLY:
        return LoadedRunMaterial(record, definition, config)
    raise ValueError("run has unsupported world material kind")
