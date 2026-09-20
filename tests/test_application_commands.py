# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn
from uuid import UUID

import pytest

from grass.application import HistoryScope, LocalSimulationApplication
from grass.core import (
    BoundedReaction,
    BranchId,
    DecisionInvoker,
    DecisionOutcomeKind,
    DecisionPointId,
    DecisionProposal,
    DecisionProviderBinding,
    DecisionProviderRouting,
    DecisionRequest,
    EntityId,
    EventId,
    EventStore,
    EventToCommit,
    JobId,
    LogicalTime,
    ObservationId,
    PlanStepRef,
    Provenance,
    ProviderBindingConfiguration,
    ProviderBindingId,
    ProviderExecutionLocation,
    SimulationRunConfig,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    WorldDefinition,
)
from grass.persistence import (
    RunId,
    SimulationRunRecord,
    SqlitePersistence,
    WorldMaterialKind,
)
from grass.providers import HumanDecisionInvoker
from grass.runtime import (
    RuntimeIdentitySource,
    RuntimeIntegrityError,
    RuntimeWorkKind,
    SimulationEngine,
    UuidRuntimeIdentitySource,
)
from grass.worlds import (
    FilesystemWorldSnapshotStore,
    WorldSnapshotNotFoundError,
    load_world_package,
    register_world_package_run,
)
from tests.test_runtime_engine import (
    DecisionPointTrigger,
    FailingWorldResolver,
    GenesisPerception,
    NoJobStarts,
    NoScenarioResolver,
    NoSchedule,
)
from tests.test_world_packages import write_world_package


class FailingInitializationIds(UuidRuntimeIdentitySource):
    def transition_id(self, branch_id: BranchId, work_kind: RuntimeWorkKind, /) -> TransitionId:
        del branch_id, work_kind
        raise RuntimeError("interrupted initialization")


class NoAllocationIds:
    @staticmethod
    def _fail() -> NoReturn:
        raise AssertionError("status inspection must not allocate identities")

    def transition_id(self, branch_id: BranchId, work_kind: RuntimeWorkKind, /) -> TransitionId:
        del branch_id, work_kind
        self._fail()

    def event_ids(self, count: int, /) -> tuple[EventId, ...]:
        del count
        self._fail()

    def job_id(self, plan_step_ref: PlanStepRef, /) -> JobId:
        del plan_step_ref
        self._fail()

    def observation_id(self, source_event_id: EventId, actor_id: EntityId, /) -> ObservationId:
        del source_event_id, actor_id
        self._fail()

    def decision_point_id(self, observation_id: ObservationId, /) -> DecisionPointId:
        del observation_id
        self._fail()


class ImmediateHumanSource:
    def __init__(self) -> None:
        self.requests: list[DecisionRequest] = []

    async def acquire(self, request: DecisionRequest, /) -> DecisionProposal:
        self.requests.append(request)
        return DecisionProposal(
            DecisionOutcomeKind.BOUNDED_REACTION,
            bounded_reaction=BoundedReaction("Acknowledge the observation"),
        )


class DecisionRuntimeComposer:
    def validate(
        self,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        /,
    ) -> None:
        if run_config.world_definition_ref != world_definition.ref:
            raise ValueError("run config must reference world definition")

    def compose(
        self,
        *,
        event_store: EventStore,
        world_definition: WorldDefinition,
        run_config: SimulationRunConfig,
        identity_source: RuntimeIdentitySource,
        decision_invokers: Mapping[ProviderBindingId, DecisionInvoker] | None = None,
    ) -> SimulationEngine:
        self.validate(world_definition, run_config)
        return SimulationEngine(
            event_store=event_store,
            world_definition=world_definition,
            run_config=run_config,
            identity_source=identity_source,
            schedule_projector=NoSchedule(),
            conflict_predicate=lambda _left, _right: False,
            world_resolution_provider=FailingWorldResolver(),
            scenario_occurrence_resolution_provider=NoScenarioResolver(),
            perception_projector=GenesisPerception(),
            decision_trigger_policy=DecisionPointTrigger(),
            decision_invokers={} if decision_invokers is None else decision_invokers,
            job_start_policy=NoJobStarts(),
        )


def _application(tmp_path: Path) -> LocalSimulationApplication:
    return LocalSimulationApplication(
        SqlitePersistence(tmp_path / "grass.db"),
        FilesystemWorldSnapshotStore(tmp_path / "world_snapshots"),
    )


def test_create_generates_safe_distinct_uuid_runs_and_reopens_without_authors(
    tmp_path: Path,
) -> None:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    author, _, _, _ = write_world_package(worlds)
    package = load_world_package(author)
    config = SimulationRunConfig(package.world_definition.ref)
    application = _application(tmp_path)

    first = application.create_run(package, config)
    second = application.create_run(package, config)

    assert first.run_id != second.run_id
    assert str(UUID(first.run_id.value)) == first.run_id.value
    assert str(UUID(second.run_id.value)) == second.run_id.value
    assert first.root_branch_id == BranchId("root")
    assert not hasattr(first, "engine")
    assert not hasattr(first, "event_store")
    shutil.rmtree(author)

    reopened = _application(tmp_path).open_run(first.run_id)
    assert reopened.run_id == first.run_id
    assert reopened.inspect_status().value == "READY"


def test_registered_empty_root_survives_interruption_and_open_recovers(
    tmp_path: Path,
) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    config = SimulationRunConfig(package.world_definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    interrupted = LocalSimulationApplication(
        persistence,
        snapshots,
        identity_source_factory=FailingInitializationIds,
    )

    with pytest.raises(RuntimeError, match="interrupted initialization"):
        interrupted.create_run(package, config)

    records = persistence.list_runs()
    assert len(records) == 1
    store = persistence.event_store(records[0].run_id)
    assert store.read_transitions(BranchId("root")) == ()

    recovered = LocalSimulationApplication(persistence, snapshots).open_run(records[0].run_id)
    assert len(store.read_transitions(recovered.root_branch_id)) == 1


def test_open_rejects_invalid_nonempty_root(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    config = SimulationRunConfig(package.world_definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    record = SimulationRunRecord(
        RunId("invalid-run"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime.now(UTC),
    )
    register_world_package_run(persistence, snapshots, record, package, config)
    persistence.event_store(record.run_id).commit_transition(
        TransitionToCommit(
            TransitionRef(record.root_branch_id, TransitionId("invalid")),
            LogicalTime(0),
            (EventToCommit(EventId("invalid"), "Unexpected", 1, {}, Provenance("ENGINE")),),
        )
    )

    with pytest.raises(RuntimeIntegrityError, match="malformed genesis"):
        LocalSimulationApplication(persistence, snapshots).open_run(record.run_id)


def test_open_material_behavior_follows_only_persisted_kind(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    config = SimulationRunConfig(package.world_definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    definition_only = SimulationRunRecord(
        RunId("definition-only"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.DEFINITION_ONLY,
        datetime.now(UTC),
    )
    persistence.register_run(definition_only, package.world_definition, config)

    opened = LocalSimulationApplication(persistence, snapshots).open_run(definition_only.run_id)
    assert opened.run_id == definition_only.run_id

    package_record = SimulationRunRecord(
        RunId("missing-package"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.PACKAGE_SNAPSHOT,
        datetime.now(UTC),
    )
    persistence.register_run(package_record, package.world_definition, config)
    with pytest.raises(WorldSnapshotNotFoundError):
        LocalSimulationApplication(persistence, snapshots).open_run(package_record.run_id)


def test_package_registration_rejects_definition_only_record_before_publish(
    tmp_path: Path,
) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    config = SimulationRunConfig(package.world_definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    record = SimulationRunRecord(
        RunId("wrong-kind"),
        BranchId("root"),
        package.world_definition.ref,
        WorldMaterialKind.DEFINITION_ONLY,
        datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="PACKAGE_SNAPSHOT"):
        register_world_package_run(persistence, snapshots, record, package, config)

    assert persistence.list_runs() == ()
    assert not (snapshots.root / record.run_id.value).exists()


def test_opened_run_creates_branch_at_exact_historical_position(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    application = _application(tmp_path)
    opened = application.create_run(package, SimulationRunConfig(package.world_definition.ref))
    genesis = application.queries.get_branch(opened.run_id).position.history_position
    result = asyncio.run(opened.step())
    assert result.committed_transition is not None

    branch = opened.create_branch(BranchId("historical"), genesis)
    assert branch.fork_position == genesis
    child_result = asyncio.run(opened.step(BranchId("historical")))
    assert child_result.committed_transition is not None

    reopened = application.open_run(opened.run_id)
    assert reopened.inspect_status().value == "QUIESCENT"
    assert reopened.inspect_status(BranchId("historical")).value == "QUIESCENT"
    history = application.queries.get_history(opened.run_id, BranchId("historical"))
    assert history.position.history_position.transition_ref != genesis.transition_ref
    root_origin = application.queries.get_history(
        opened.run_id,
        scope=HistoryScope.BRANCH_ORIGIN,
    )
    child_origin = application.queries.get_history(
        opened.run_id,
        BranchId("historical"),
        scope=HistoryScope.BRANCH_ORIGIN,
    )
    assert len(root_origin.transitions) == 2
    assert len(child_origin.transitions) == 1


def test_application_executes_server_managed_human_decision(tmp_path: Path) -> None:
    document: dict[str, object] = {
        "world_definition_id": "decision-world",
        "version": "1.0",
        "schema_version": 3,
        "vocabulary": {
            "entity_types": ["Person"],
            "relation_types": [],
            "resource_types": [],
            "state_variable_types": [],
        },
        "initial_conditions": {
            "logical_time": 0,
            "entities": [{"entity_id": "actor", "entity_type": "Person", "properties": {}}],
            "relations": [],
            "resources": [],
            "state_variables": [],
        },
        "metadata": {},
        "scenario_event_rules": [],
    }
    author, _, _, _ = write_world_package(
        tmp_path,
        name="decision-world",
        document=document,
    )
    package = load_world_package(author)
    binding_id = ProviderBindingId("human")
    binding = DecisionProviderBinding(
        binding_id,
        "human",
        ProviderExecutionLocation.SERVER_MANAGED,
    )
    config = SimulationRunConfig(
        package.world_definition.ref,
        ProviderBindingConfiguration(
            DecisionProviderRouting(binding_id),
            {binding_id: binding},
        ),
    )
    source = ImmediateHumanSource()
    application = LocalSimulationApplication(
        SqlitePersistence(tmp_path / "grass.db"),
        FilesystemWorldSnapshotStore(tmp_path / "world_snapshots"),
        composer=DecisionRuntimeComposer(),
        decision_invokers={binding_id: HumanDecisionInvoker(source, binding)},
    )
    opened = application.create_run(package, config)

    perception = asyncio.run(opened.step())
    decision = asyncio.run(opened.step())

    assert perception.work_kind is RuntimeWorkKind.PERCEPTION
    assert decision.work_kind is RuntimeWorkKind.DECISION
    assert len(source.requests) == 1
    decisions = application.queries.get_decisions(opened.run_id)
    assert len(decisions) == 1
    assert decisions[0].decision is not None


def test_query_status_delegates_without_identity_allocation(tmp_path: Path) -> None:
    author, _, _, _ = write_world_package(tmp_path)
    package = load_world_package(author)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    snapshots = FilesystemWorldSnapshotStore(tmp_path / "world_snapshots")
    created = LocalSimulationApplication(persistence, snapshots).create_run(
        package, SimulationRunConfig(package.world_definition.ref)
    )
    inspecting = LocalSimulationApplication(
        persistence,
        snapshots,
        identity_source_factory=NoAllocationIds,
    )

    assert inspecting.queries.get_status(created.run_id).value == "READY"
