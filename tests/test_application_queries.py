# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from grass.application import (
    ActorHistoryAttributionKind,
    ActorMembershipEvidence,
    DecisionStatus,
    HistoryScope,
    LocalSimulationApplication,
    LocalSimulationQueries,
    QueryError,
    QueryNotFoundError,
)
from grass.core import (
    BranchId,
    CommittedTransition,
    DecisionPointId,
    EntityId,
    EventId,
    EventPayload,
    EventStore,
    EventToCommit,
    HistoryPosition,
    JobId,
    LogicalTime,
    PlanId,
    PlanStepId,
    Provenance,
    SimulationRunConfig,
    TransitionId,
    TransitionRef,
    TransitionToCommit,
    WorldDefinition,
    build_genesis_transition,
    load_world_definition,
)
from grass.core.cognition_events import (
    DECISION_POINT_CREATED,
    DECISION_RECORDED,
    OBSERVATION_CREATED,
)
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_COMPLETED,
    JOB_CREATED,
    JOB_PROGRESS_UPDATED,
    PLAN_CREATED,
)
from grass.core.resolution_events import RESOLUTION_OUTCOME_RECORDED
from grass.core.world_events import ENTITY_UPDATED
from grass.persistence import RunId, SimulationRunRecord, SqlitePersistence, WorldMaterialKind
from grass.worlds import FilesystemWorldSnapshotStore

ROOT = BranchId("root")
ACTOR = EntityId("actor")
RUN_ID = RunId("query-run")


def _definition() -> WorldDefinition:
    return load_world_definition(
        {
            "world_definition_id": "query-world",
            "version": "1.0",
            "schema_version": 1,
            "vocabulary": {
                "entity_types": ["Person"],
                "relation_types": [],
                "resource_types": [],
                "state_variable_types": [],
            },
            "initial_conditions": {
                "logical_time": 0,
                "entities": [
                    {"entity_id": "actor", "entity_type": "Person", "properties": {}},
                    {"entity_id": "not-actor", "entity_type": "Person", "properties": {}},
                ],
                "relations": [],
                "resources": [],
                "state_variables": [],
            },
            "metadata": {},
        }
    )


def _event(label: str, event_type: str, payload: EventPayload) -> EventToCommit:
    return EventToCommit(EventId(label), event_type, 1, payload, Provenance("ENGINE"))


def _commit(
    store: EventStore,
    label: str,
    events: tuple[EventToCommit, ...],
    branch: BranchId = ROOT,
) -> CommittedTransition:
    return store.commit_transition(
        TransitionToCommit(
            TransitionRef(branch, TransitionId(label)),
            LogicalTime(1),
            events,
        )
    )


def _plan_snapshot() -> EventPayload:
    return cast(
        EventPayload,
        {
            "plan_id": "plan",
            "version": 1,
            "actor_id": ACTOR.value,
            "objective": "wait safely",
            "steps": [
                {
                    "step_id": "step",
                    "primitive": "WAIT",
                    "blueprint_ref": None,
                    "bindings": {},
                    "parameters": {},
                    "dependencies": [],
                    "origin": "ACTOR_INTENT",
                    "description": None,
                }
            ],
            "replaces_plan_ref": None,
        },
    )


def populated_queries(
    tmp_path: Path,
) -> tuple[LocalSimulationQueries, EventStore, HistoryPosition, HistoryPosition]:
    definition = _definition()
    config = SimulationRunConfig(definition.ref)
    persistence = SqlitePersistence(tmp_path / "grass.db")
    persistence.register_run(
        SimulationRunRecord(
            RUN_ID,
            ROOT,
            definition.ref,
            WorldMaterialKind.DEFINITION_ONLY,
            datetime.now(UTC),
        ),
        definition,
        config,
    )
    store = persistence.event_store(RUN_ID)
    store.commit_transition(
        build_genesis_transition(
            definition,
            config,
            TransitionRef(ROOT, TransitionId("genesis")),
            (EventId("genesis"), EventId("actor"), EventId("not-actor")),
        )
    )
    historical = store.head_position(ROOT)
    _commit(
        store,
        "actor-material",
        (
            _event("plan", PLAN_CREATED, {"plan": _plan_snapshot()}),
            _event(
                "entity-update",
                ENTITY_UPDATED,
                {"entity_id": ACTOR.value, "properties_after": {"ready": True}},
            ),
            _event(
                "observation",
                OBSERVATION_CREATED,
                {"observation_id": "observation", "actor_id": ACTOR.value, "content": {}},
            ),
        ),
    )
    fork_position = store.head_position(ROOT)
    store.fork_branch(BranchId("child"), fork_position)
    _commit(
        store,
        "decision-point",
        (
            _event(
                "decision-point",
                DECISION_POINT_CREATED,
                {
                    "decision_point_id": "decision",
                    "actor_id": ACTOR.value,
                    "reason": "MATERIAL_OBSERVATION",
                    "scope": "BOUNDED",
                    "observation_ids": ["observation"],
                    "subject_plan_ref": None,
                },
            ),
        ),
    )
    _commit(
        store,
        "decision",
        (
            _event(
                "decision",
                DECISION_RECORDED,
                {
                    "decision_point_id": "decision",
                    "outcome": {
                        "kind": "BOUNDED_REACTION",
                        "bounded_reaction": {
                            "intent_description": "acknowledge",
                            "content": None,
                        },
                    },
                },
            ),
        ),
    )
    _commit(
        store,
        "job-start",
        (
            _event(
                "job-created",
                JOB_CREATED,
                {
                    "job_id": "job",
                    "plan_step_ref": {
                        "plan_ref": {"plan_id": "plan", "version": 1},
                        "step_id": "step",
                    },
                    "progress": {"kind": "BINARY", "complete": False},
                },
            ),
            _event("job-active", JOB_ACTIVATED, {"job_id": "job"}),
        ),
    )
    _commit(
        store,
        "job-resolution",
        (
            _event(
                "resolution",
                RESOLUTION_OUTCOME_RECORDED,
                {"job_id": "job", "outcome": "SUCCESS"},
            ),
            _event(
                "job-progress",
                JOB_PROGRESS_UPDATED,
                {"job_id": "job", "progress_after": {"kind": "BINARY", "complete": True}},
            ),
            _event("job-completed", JOB_COMPLETED, {"job_id": "job"}),
        ),
    )
    _commit(
        store,
        "child-observation",
        (
            _event(
                "child-observation",
                OBSERVATION_CREATED,
                {
                    "observation_id": "child-observation",
                    "actor_id": ACTOR.value,
                    "content": {},
                },
            ),
        ),
        BranchId("child"),
    )
    application = LocalSimulationApplication(
        persistence,
        FilesystemWorldSnapshotStore(tmp_path / "snapshots"),
    )
    return application.queries, store, historical, fork_position


def test_queries_are_exact_immutable_and_child_history_is_frozen(tmp_path: Path) -> None:
    queries, store, historical, fork_position = populated_queries(tmp_path)
    run = queries.get_run(RUN_ID)
    runs = queries.list_runs()
    branches = queries.list_branches(RUN_ID)
    root = queries.get_history(RUN_ID, ROOT)
    child = queries.get_history(RUN_ID, BranchId("child"))
    origin = queries.get_history(RUN_ID, BranchId("child"), scope=HistoryScope.BRANCH_ORIGIN)

    assert runs == (run,)
    assert tuple(item.branch.branch_id for item in branches) == (
        BranchId("child"),
        ROOT,
    )
    assert branches[0].visible_transition_count == 3
    assert branches[0].origin_transition_count == 1
    assert branches[1].visible_transition_count == 6
    assert branches[1].origin_transition_count == 6
    assert type(root.transitions) is tuple
    assert child.transitions[:2] == tuple(store.read_visible_transitions(fork_position))
    assert tuple(item.transition_id.value for item in origin.transitions) == ("child-observation",)
    old_state = queries.get_state(RUN_ID, ROOT, position=historical)
    assert old_state.position.history_position == historical
    assert old_state.state.execution.plans == {}
    with pytest.raises(QueryError, match="explicit position branch"):
        queries.get_state(RUN_ID, ROOT, position=child.position.history_position)
    with pytest.raises(QueryNotFoundError, match="simulation run"):
        queries.get_run(RunId("missing"))
    with pytest.raises(QueryNotFoundError, match="branch or history"):
        queries.get_branch(RUN_ID, BranchId("missing"))
    with pytest.raises(TypeError):
        cast(list[object], root.transitions)[0] = object()


def test_jobs_decisions_actors_and_mechanical_actor_history(tmp_path: Path) -> None:
    queries, _, _, _ = populated_queries(tmp_path)
    jobs = queries.get_jobs(RUN_ID, ROOT)
    decisions = queries.get_decisions(RUN_ID, ROOT)
    actors = queries.get_actors(RUN_ID, ROOT)

    assert len(jobs) == 1
    assert jobs[0].job.job_id == JobId("job")
    assert queries.get_job(RUN_ID, ROOT, JobId("job")) == jobs[0]
    assert jobs[0].plan.plan_id == PlanId("plan")
    assert jobs[0].step.step_id == PlanStepId("step")
    assert decisions[0].status is DecisionStatus.RESOLVED
    assert queries.get_decision(RUN_ID, ROOT, DecisionPointId("decision")) == decisions[0]
    assert len(actors) == 1
    assert actors[0].actor_id == ACTOR
    assert actors[0].evidence == (
        ActorMembershipEvidence.PLAN,
        ActorMembershipEvidence.OBSERVATION,
        ActorMembershipEvidence.DECISION_POINT,
    )
    assert not hasattr(actors[0], "provider")
    assert not hasattr(actors[0], "memory")
    assert queries.get_actor(RUN_ID, ROOT, ACTOR) == actors[0]
    assert queries.get_actor_observations(RUN_ID, ROOT, ACTOR) == actors[0].observations
    assert queries.get_actor_decisions(RUN_ID, ROOT, ACTOR) == actors[0].decisions
    assert queries.get_actor_plans(RUN_ID, ROOT, ACTOR) == actors[0].plans
    assert queries.get_actor_jobs(RUN_ID, ROOT, ACTOR) == actors[0].jobs
    with pytest.raises(QueryNotFoundError, match="Job"):
        queries.get_job(RUN_ID, ROOT, JobId("missing"))
    with pytest.raises(QueryNotFoundError, match="DecisionPoint"):
        queries.get_decision(RUN_ID, ROOT, DecisionPointId("missing"))
    with pytest.raises(QueryNotFoundError, match="actor"):
        queries.get_actor(RUN_ID, ROOT, EntityId("not-actor"))

    history = queries.get_actor_history(RUN_ID, ROOT, ACTOR)
    kinds = tuple(attribution.kind for entry in history for attribution in entry.attributions)
    assert ActorHistoryAttributionKind.OBSERVATION in kinds
    assert ActorHistoryAttributionKind.DECISION_POINT in kinds
    assert ActorHistoryAttributionKind.DECISION in kinds
    assert ActorHistoryAttributionKind.PLAN in kinds
    assert ActorHistoryAttributionKind.JOB in kinds
    assert ActorHistoryAttributionKind.JOB_RESOLUTION in kinds
    actor_material = next(
        entry
        for entry in history
        if entry.transition.transition_id == TransitionId("actor-material")
    )
    assert len(actor_material.transition.events) == 3
    assert {item.event_id for item in actor_material.attributions} == {
        EventId("plan"),
        EventId("observation"),
    }
