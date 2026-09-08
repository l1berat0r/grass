# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence

import pytest

from grass.core import (
    BranchId,
    CommittedTransition,
    EventPayload,
    HistoryPosition,
    InMemoryEventStore,
    JobId,
    JobStatus,
    PlanId,
    PlanRef,
    ProjectionError,
    StateCheckpoint,
    project_transition,
    replay_branch,
)
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_CREATED,
    JOB_FAILED,
    JOB_PROGRESS_UPDATED,
    PLAN_CREATED,
    PLAN_REPLACED,
    PLAN_REVISED,
)
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def plan_snapshot(
    plan_id: str = "plan",
    step_id: str = "step",
    *,
    version: int = 1,
    replaces: EventPayload | None = None,
) -> EventPayload:
    return {
        "plan_id": plan_id,
        "version": version,
        "actor_id": "actor",
        "objective": "Execute",
        "steps": [
            {
                "step_id": step_id,
                "primitive": "WAIT",
                "blueprint_ref": None,
                "bindings": {},
                "parameters": {},
                "dependencies": [],
                "origin": "ACTOR_INTENT",
                "description": None,
            }
        ],
        "replaces_plan_ref": replaces,
    }


def commit(
    store: InMemoryEventStore,
    branch: str,
    label: str,
    time: int,
    events: Sequence[tuple[str, EventPayload]],
) -> CommittedTransition:
    return store.commit_transition(
        transition_to_commit(
            branch,
            label,
            time,
            [
                event_to_commit(
                    f"{branch}:{label}:{index}",
                    event_type=event_type,
                    payload=payload,
                )
                for index, (event_type, payload) in enumerate(events)
            ],
        )
    )


def root_execution_history(
    store: InMemoryEventStore,
) -> tuple[CommittedTransition, CommittedTransition, CommittedTransition]:
    entity = commit(
        store,
        "root",
        "entity",
        0,
        [
            (
                ENTITY_CREATED,
                {"entity_id": "actor", "entity_type": "Person", "properties": {}},
            )
        ],
    )
    plan = commit(
        store,
        "root",
        "plan",
        1,
        [(PLAN_CREATED, {"plan": plan_snapshot()})],
    )
    job = commit(
        store,
        "root",
        "job",
        2,
        [
            (
                JOB_CREATED,
                {
                    "job_id": "job",
                    "plan_step_ref": {
                        "plan_ref": {"plan_id": "plan", "version": 1},
                        "step_id": "step",
                    },
                    "progress": {"kind": "LINEAR", "completed": 0, "total": 5},
                },
            )
        ],
    )
    return entity, plan, job


def test_incremental_execution_projection_matches_full_replay() -> None:
    store = rooted_store("root")
    branch_id = stable_id(BranchId, "root")
    history = root_execution_history(store)
    active = commit(
        store,
        "root",
        "active",
        3,
        [
            (JOB_ACTIVATED, {"job_id": "job"}),
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 2, "total": 5},
                },
            ),
        ],
    )
    incremental = replay_branch(
        store,
        HistoryPosition(branch_id, history[-1].transition_ref),
    )
    incremental = project_transition(incremental, active)

    replayed = replay_branch(store, store.head_position(branch_id))

    assert incremental == replayed
    assert replayed.execution.jobs[JobId("job")].status is JobStatus.ACTIVE


def test_parent_and_child_job_lifecycle_are_isolated() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    _, _, job = root_execution_history(store)
    store.fork_branch(child_id, HistoryPosition(root_id, job.transition_ref))
    commit(store, "root", "activate", 3, [(JOB_ACTIVATED, {"job_id": "job"})])
    commit(store, "child", "fail", 3, [(JOB_FAILED, {"job_id": "job"})])

    parent = replay_branch(store, store.head_position(root_id))
    child = replay_branch(store, store.head_position(child_id))

    assert parent.execution.jobs[JobId("job")].status is JobStatus.ACTIVE
    assert child.execution.jobs[JobId("job")].status is JobStatus.FAILED
    assert (
        parent.execution.jobs[JobId("job")].plan_step_ref
        == child.execution.jobs[JobId("job")].plan_step_ref
    )


def test_inherited_job_blocks_a_second_job_for_revised_logical_step() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    _, _, job = root_execution_history(store)
    store.fork_branch(child_id, HistoryPosition(root_id, job.transition_ref))
    commit(
        store,
        "child",
        "revise",
        3,
        [(PLAN_REVISED, {"plan": plan_snapshot(version=2)})],
    )
    commit(
        store,
        "child",
        "second-job",
        4,
        [
            (
                JOB_CREATED,
                {
                    "job_id": "second-job",
                    "plan_step_ref": {
                        "plan_ref": {"plan_id": "plan", "version": 2},
                        "step_id": "step",
                    },
                    "progress": {"kind": "BINARY", "complete": False},
                },
            )
        ],
    )

    with pytest.raises(ProjectionError, match="at most one Job"):
        replay_branch(store, store.head_position(child_id))


def test_descendants_may_replace_the_same_inherited_plan_differently() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    _, plan, _ = root_execution_history(store)
    store.fork_branch(child_id, HistoryPosition(root_id, plan.transition_ref))
    commit(
        store,
        "root",
        "replace-parent",
        3,
        [
            (
                PLAN_REPLACED,
                {
                    "plan": plan_snapshot(
                        "parent-plan",
                        "parent-step",
                        replaces={"plan_id": "plan", "version": 1},
                    )
                },
            )
        ],
    )
    commit(
        store,
        "child",
        "replace-child",
        3,
        [
            (
                PLAN_REPLACED,
                {
                    "plan": plan_snapshot(
                        "child-plan",
                        "child-step",
                        replaces={"plan_id": "plan", "version": 1},
                    )
                },
            )
        ],
    )

    parent = replay_branch(store, store.head_position(root_id))
    child = replay_branch(store, store.head_position(child_id))

    assert PlanRef(PlanId("parent-plan"), 1) in parent.execution.plans
    assert PlanRef(PlanId("child-plan"), 1) not in parent.execution.plans
    assert PlanRef(PlanId("child-plan"), 1) in child.execution.plans
    assert PlanRef(PlanId("parent-plan"), 1) not in child.execution.plans


class StaticCheckpointLoader:
    def __init__(self, checkpoint: StateCheckpoint) -> None:
        self.checkpoint = checkpoint

    def load_checkpoint(self, target: HistoryPosition, /) -> StateCheckpoint | None:
        return self.checkpoint


def test_checkpoint_replay_preserves_execution_state() -> None:
    store = rooted_store("root")
    root_id = stable_id(BranchId, "root")
    _, plan, _ = root_execution_history(store)
    checkpoint_position = HistoryPosition(root_id, plan.transition_ref)
    checkpoint = StateCheckpoint(
        checkpoint_position,
        replay_branch(store, checkpoint_position),
    )
    target = store.head_position(root_id)

    assert replay_branch(store, target, StaticCheckpointLoader(checkpoint)) == replay_branch(
        store, target
    )
