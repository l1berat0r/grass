# SPDX-License-Identifier: GPL-3.0-only

"""Storage-neutral contracts for durable local simulation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from grass.core.identifiers import BranchId
from grass.core.world_definitions import (
    SimulationRunConfig,
    WorldDefinition,
    WorldDefinitionRef,
)


class PersistenceError(RuntimeError):
    """Durable storage could not complete a requested operation."""


class PersistenceIntegrityError(PersistenceError):
    """Persisted data violates the supported storage or domain contracts."""


class UnsupportedStorageVersionError(PersistenceError):
    """A database or stored document uses an unsupported future version."""


class RunNotFoundError(PersistenceError, LookupError):
    """The requested durable simulation run does not exist."""


@dataclass(frozen=True, slots=True)
class RunId:
    """Opaque operational identity of one simulation run."""

    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str:
            raise TypeError("run identifier value must be a string")
        if self.value == "":
            raise ValueError("run identifier value must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SimulationRunRecord:
    """Minimal operational metadata for one durable simulation run."""

    run_id: RunId
    root_branch_id: BranchId
    world_definition_ref: WorldDefinitionRef
    created_at: datetime

    def __post_init__(self) -> None:
        if type(self.run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        if type(self.root_branch_id) is not BranchId:
            raise TypeError("root_branch_id must be a BranchId")
        if type(self.world_definition_ref) is not WorldDefinitionRef:
            raise TypeError("world_definition_ref must be a WorldDefinitionRef")
        if type(self.created_at) is not datetime:
            raise TypeError("created_at must be a datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


class RunRepository(Protocol):
    """Persist and retrieve complete immutable run registration material."""

    def register_run(
        self,
        record: SimulationRunRecord,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None: ...

    def read_run(self, run_id: RunId, /) -> SimulationRunRecord: ...


class WorldDefinitionSnapshotRepository(Protocol):
    """Retrieve the exact canonical WorldDefinition associated with a run."""

    def read_world_definition(self, run_id: RunId, /) -> WorldDefinition: ...


class RunConfigSnapshotRepository(Protocol):
    """Retrieve one run's immutable non-secret execution configuration."""

    def read_run_config(self, run_id: RunId, /) -> SimulationRunConfig: ...
