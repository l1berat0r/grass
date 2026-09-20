# SPDX-License-Identifier: GPL-3.0-only

"""Write-side local simulation use cases above the engine authority boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from grass.application._material import LocalSimulationStorage, load_run_material
from grass.application.contracts import VerificationReport
from grass.application.queries import LocalSimulationQueries
from grass.application.verification import LocalSimulationVerifier
from grass.core.branches import Branch, HistoryPosition
from grass.core.decision_invocations import DecisionInvoker
from grass.core.identifiers import BranchId, ProviderBindingId
from grass.core.logical_time import LogicalTime
from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.persistence.contracts import (
    RunId,
    SimulationRunRecord,
    WorldMaterialKind,
)
from grass.runtime.composition import RuntimeComposer
from grass.runtime.contracts import (
    AdvanceResult,
    RunStatus,
    RuntimeIdentitySource,
    StepResult,
)
from grass.runtime.engine import SimulationEngine
from grass.runtime.identities import UuidRuntimeIdentitySource
from grass.runtime.initialization import initialize_root
from grass.worlds.composition import OccurrenceRuntimeComposer
from grass.worlds.package import WorldPackage
from grass.worlds.snapshots import (
    FilesystemWorldSnapshotStore,
    register_world_package_run,
)


class OpenedRun:
    """Opaque authority-preserving handle to one initialized local run."""

    __slots__ = ("_engine", "_root_branch_id", "_run_id", "_verifier")

    def __init__(
        self,
        run_id: RunId,
        root_branch_id: BranchId,
        engine: SimulationEngine,
        verifier: LocalSimulationVerifier,
    ) -> None:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        if type(root_branch_id) is not BranchId:
            raise TypeError("root_branch_id must be a BranchId")
        if not isinstance(engine, SimulationEngine):
            raise TypeError("engine must be a SimulationEngine")
        self._run_id = run_id
        self._root_branch_id = root_branch_id
        self._engine = engine
        self._verifier = verifier

    @property
    def run_id(self) -> RunId:
        return self._run_id

    @property
    def root_branch_id(self) -> BranchId:
        return self._root_branch_id

    async def step(
        self,
        branch_id: BranchId | None = None,
        *,
        target_time: LogicalTime | None = None,
    ) -> StepResult:
        return await self._engine.step(
            self._root_branch_id if branch_id is None else branch_id,
            target_time=target_time,
        )

    async def advance(
        self,
        branch_id: BranchId | None = None,
        *,
        target_time: LogicalTime | None = None,
        max_steps: int = 1000,
    ) -> AdvanceResult:
        return await self._engine.advance(
            self._root_branch_id if branch_id is None else branch_id,
            target_time=target_time,
            max_steps=max_steps,
        )

    def create_branch(
        self,
        branch_id: BranchId,
        fork_position: HistoryPosition,
        /,
    ) -> Branch:
        return self._engine.create_branch(branch_id, fork_position)

    def inspect_status(self, branch_id: BranchId | None = None) -> RunStatus:
        return self._engine.inspect_status(self._root_branch_id if branch_id is None else branch_id)

    def verify(self) -> VerificationReport:
        return self._verifier.verify_run(self._run_id)


class LocalSimulationApplication:
    """Create, recover, open, execute, and inspect durable local simulations."""

    def __init__(
        self,
        storage: LocalSimulationStorage,
        snapshot_store: FilesystemWorldSnapshotStore,
        *,
        composer: RuntimeComposer | None = None,
        identity_source_factory: Callable[[], RuntimeIdentitySource] = UuidRuntimeIdentitySource,
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
    ) -> None:
        required_storage_methods = (
            "register_run",
            "read_run",
            "list_runs",
            "read_world_definition",
            "read_run_config",
            "event_store",
        )
        if not all(callable(getattr(storage, name, None)) for name in required_storage_methods):
            raise TypeError("storage must implement local run persistence repositories")
        if not isinstance(snapshot_store, FilesystemWorldSnapshotStore):
            raise TypeError("snapshot_store must be a FilesystemWorldSnapshotStore")
        selected_composer = OccurrenceRuntimeComposer() if composer is None else composer
        if not callable(getattr(selected_composer, "validate", None)) or not callable(
            getattr(selected_composer, "compose", None)
        ):
            raise TypeError("composer must implement RuntimeComposer")
        if not callable(identity_source_factory):
            raise TypeError("identity_source_factory must be callable")
        invokers = {} if decision_invokers is None else dict(decision_invokers)
        if not all(type(key) is ProviderBindingId for key in invokers):
            raise TypeError("decision_invokers must use ProviderBindingId keys")
        if not all(callable(getattr(value, "invoke", None)) for value in invokers.values()):
            raise TypeError("decision_invokers values must provide invoke")

        self._storage = storage
        self._snapshot_store = snapshot_store
        self._composer = selected_composer
        self._identity_source_factory = identity_source_factory
        self._decision_invokers = MappingProxyType(invokers)
        self._verifier = LocalSimulationVerifier(storage, snapshot_store)
        self._queries = LocalSimulationQueries(
            storage,
            snapshot_store,
            composer=selected_composer,
            identity_source_factory=identity_source_factory,
            decision_invokers=self._decision_invokers,
        )

    @property
    def queries(self) -> LocalSimulationQueries:
        return self._queries

    def _opened(
        self,
        record: SimulationRunRecord,
        package_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        identity_source: RuntimeIdentitySource,
    ) -> OpenedRun:
        engine = self._composer.compose(
            event_store=self._storage.event_store(record.run_id),
            world_definition=package_definition,
            run_config=run_config,
            identity_source=identity_source,
            decision_invokers=self._decision_invokers,
        )
        return OpenedRun(record.run_id, record.root_branch_id, engine, self._verifier)

    def create_run(
        self,
        package: WorldPackage,
        run_config: SimulationRunConfig,
        /,
    ) -> OpenedRun:
        if type(package) is not WorldPackage:
            raise TypeError("package must be a WorldPackage")
        if type(run_config) is not SimulationRunConfig:
            raise TypeError("run_config must be a SimulationRunConfig")
        definition = package.world_definition
        self._composer.validate(definition, run_config)

        run_id = RunId(str(uuid4()))
        record = SimulationRunRecord(
            run_id,
            BranchId("root"),
            definition.ref,
            WorldMaterialKind.PACKAGE_SNAPSHOT,
            datetime.now(UTC),
        )
        register_world_package_run(
            self._storage,
            self._snapshot_store,
            record,
            package,
            run_config,
        )
        event_store = self._storage.event_store(run_id)
        identity_source = self._identity_source_factory()
        initialize_root(
            event_store=event_store,
            branch_id=record.root_branch_id,
            world_definition=definition,
            run_config=run_config,
            identity_source=identity_source,
        )
        return self._opened(record, definition, run_config, identity_source)

    def open_run(self, run_id: RunId, /) -> OpenedRun:
        if type(run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        material = load_run_material(self._storage, self._snapshot_store, run_id)
        self._composer.validate(material.definition, material.config)
        identity_source = self._identity_source_factory()
        initialize_root(
            event_store=self._storage.event_store(run_id),
            branch_id=material.record.root_branch_id,
            world_definition=material.definition,
            run_config=material.config,
            identity_source=identity_source,
        )
        return self._opened(
            material.record,
            material.definition,
            material.config,
            identity_source,
        )

    def verify_run(self, run_id: RunId, /) -> VerificationReport:
        return self._verifier.verify_run(run_id)
