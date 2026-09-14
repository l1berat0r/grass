# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from grass.core import (
    BranchId,
    CommittedTransition,
    EventId,
    JobId,
    LogicalTime,
    ProgressAnchor,
    ResolutionProposal,
    ResolutionRequest,
    ScenarioOccurrenceResolutionProposal,
    ScenarioOccurrenceResolutionRequest,
    ScheduledResolution,
    ScriptedDecisionTriggerPolicy,
    SimulationRunConfig,
    SimulationState,
    TransitionId,
    TransitionRef,
    WorldDefinition,
    build_genesis_transition,
    load_world_definition,
    replay_branch,
)
from grass.persistence import RunId, SimulationRunRecord, SqlitePersistence
from grass.runtime import (
    JobStartProposal,
    PerceptionCandidate,
    ReadyPlanStep,
    RuntimeStopReason,
    RuntimeWorkKind,
    SimulationEngine,
    UuidRuntimeIdentitySource,
)


class NoSchedule:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> tuple[ScheduledResolution[JobId], ...]:
        del state, current_time, progress_anchors
        return ()


class NoPerception:
    def project(
        self,
        source_transition: CommittedTransition,
        state_after_source: SimulationState,
        /,
    ) -> tuple[PerceptionCandidate, ...]:
        del source_transition, state_after_source
        return ()


class NoJobStarts:
    def propose(
        self, ready_step: ReadyPlanStep, state: SimulationState, /
    ) -> JobStartProposal | None:
        del ready_step, state
        return None


class UnusedWorldResolver:
    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        del request
        raise AssertionError("world resolver must not be called")


class RecordingOccurrenceResolver:
    def __init__(self) -> None:
        self.requests: list[ScenarioOccurrenceResolutionRequest] = []

    def resolve(
        self, request: ScenarioOccurrenceResolutionRequest, /
    ) -> ScenarioOccurrenceResolutionProposal:
        self.requests.append(request)
        return ScenarioOccurrenceResolutionProposal()


def _world() -> WorldDefinition:
    return load_world_definition(
        {
            "world_definition_id": "runtime-world",
            "version": "1.0",
            "schema_version": 2,
            "vocabulary": {
                "entity_types": [],
                "relation_types": [],
                "resource_types": [],
                "state_variable_types": [],
            },
            "initial_conditions": {
                "logical_time": 0,
                "entities": [],
                "relations": [],
                "resources": [],
                "state_variables": [],
            },
            "metadata": {},
            "scenario_event_rules": [
                {
                    "rule_id": "occurrence",
                    "trigger": {"kind": "AT_TIME", "logical_time": 5},
                }
            ],
        }
    )


def _engine(
    persistence: SqlitePersistence,
    resolver: RecordingOccurrenceResolver,
) -> SimulationEngine:
    run_id = RunId("run")
    return SimulationEngine(
        event_store=persistence.event_store(run_id),
        world_definition=persistence.read_world_definition(run_id),
        run_config=persistence.read_run_config(run_id),
        identity_source=UuidRuntimeIdentitySource(),
        schedule_projector=NoSchedule(),
        conflict_predicate=lambda _left, _right: False,
        world_resolution_provider=UnusedWorldResolver(),
        scenario_occurrence_resolution_provider=resolver,
        perception_projector=NoPerception(),
        decision_trigger_policy=ScriptedDecisionTriggerPolicy({}),
        decision_invokers={},
        external_decision_bindings=frozenset(),
        job_start_policy=NoJobStarts(),
    )


def test_reopened_runtime_continues_and_replay_does_not_regenerate_occurrence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.db"
    world = _world()
    config = SimulationRunConfig(world.ref)
    record = SimulationRunRecord(
        RunId("run"), BranchId("root"), world.ref, datetime(2026, 9, 14, tzinfo=UTC)
    )
    persistence = SqlitePersistence(path)
    persistence.register_run(record, world, config)
    event_store = persistence.event_store(record.run_id)
    event_store.commit_transition(
        build_genesis_transition(
            world,
            config,
            TransitionRef(record.root_branch_id, TransitionId("genesis")),
            (EventId("genesis"),),
        )
    )

    reopened = SqlitePersistence(path)
    resolver = RecordingOccurrenceResolver()
    result = asyncio.run(_engine(reopened, resolver).step(record.root_branch_id))

    assert result.work_kind is RuntimeWorkKind.SCENARIO_OCCURRENCE
    assert result.logical_time == LogicalTime(5)
    assert len(resolver.requests) == 1
    position = reopened.event_store(record.run_id).head_position(record.root_branch_id)
    state = replay_branch(reopened.event_store(record.run_id), position)

    reopened_again = SqlitePersistence(path)
    replayed = replay_branch(
        reopened_again.event_store(record.run_id),
        reopened_again.event_store(record.run_id).head_position(record.root_branch_id),
    )
    unused_resolver = RecordingOccurrenceResolver()
    stopped = asyncio.run(_engine(reopened_again, unused_resolver).step(record.root_branch_id))

    assert replayed == state
    assert stopped.stop_reason is RuntimeStopReason.QUIESCENT
    assert unused_resolver.requests == []
