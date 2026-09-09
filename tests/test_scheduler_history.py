# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Mapping, Sequence
from typing import cast

import pytest

from grass.core import (
    BranchId,
    CommittedTransition,
    EventPayload,
    HistoryPosition,
    InMemoryEventStore,
    JobId,
    LinearProgress,
    LogicalDuration,
    LogicalTime,
    ProgressAnchor,
    ScheduledResolution,
    ScheduledResolutionIndex,
    SchedulerHistoryError,
    SimulationState,
    StateCheckpoint,
    derive_progress_anchors,
    replay_branch,
)
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_CREATED,
    JOB_PAUSED,
    JOB_PROGRESS_UPDATED,
    PLAN_CREATED,
)
from grass.core.world_events import ENTITY_CREATED, ENTITY_UPDATED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def plan_snapshot() -> EventPayload:
    return {
        "plan_id": "plan",
        "version": 1,
        "actor_id": "actor",
        "objective": "Wait",
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
    }


def commit(
    store: InMemoryEventStore,
    branch: str,
    label: str,
    logical_time: int,
    events: Sequence[tuple[str, EventPayload]],
) -> CommittedTransition:
    return store.commit_transition(
        transition_to_commit(
            branch,
            label,
            logical_time,
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


def build_active_job_history() -> tuple[InMemoryEventStore, tuple[CommittedTransition, ...]]:
    store = rooted_store("root")
    transitions = (
        commit(
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
        ),
        commit(store, "root", "plan", 1, [(PLAN_CREATED, {"plan": plan_snapshot()})]),
        commit(
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
                        "progress": {"kind": "LINEAR", "completed": 0, "total": 10},
                    },
                )
            ],
        ),
        commit(store, "root", "activate", 3, [(JOB_ACTIVATED, {"job_id": "job"})]),
    )
    return store, transitions


def branch_state(store: InMemoryEventStore, branch: str = "root") -> SimulationState:
    branch_id = stable_id(BranchId, branch)
    return replay_branch(store, store.head_position(branch_id))


def branch_history(
    store: InMemoryEventStore, branch: str = "root"
) -> tuple[CommittedTransition, ...]:
    return store.read_visible_transitions(store.head_position(stable_id(BranchId, branch)))


def test_activation_establishes_anchor_without_inferring_elapsed_progress() -> None:
    store, _ = build_active_job_history()
    commit(
        store,
        "root",
        "unrelated",
        8,
        [(ENTITY_UPDATED, {"entity_id": "actor", "properties_after": {"awake": True}})],
    )
    state = branch_state(store)

    anchors = derive_progress_anchors(state, LogicalTime(8), branch_history(store))

    assert anchors == {
        JobId("job"): ProgressAnchor(JobId("job"), LinearProgress(0, 10), LogicalTime(3))
    }
    with pytest.raises(TypeError):
        cast(dict[JobId, ProgressAnchor], anchors)[JobId("other")] = ProgressAnchor(
            JobId("other"), LinearProgress(0, 1), LogicalTime(8)
        )


def test_committed_progress_moves_anchor_and_baseline() -> None:
    store, _ = build_active_job_history()
    commit(
        store,
        "root",
        "progress",
        8,
        [
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 4, "total": 10},
                },
            )
        ],
    )

    anchors = derive_progress_anchors(branch_state(store), LogicalTime(8), branch_history(store))

    assert anchors[JobId("job")] == ProgressAnchor(
        JobId("job"), LinearProgress(4, 10), LogicalTime(8)
    )


def test_pause_excludes_job_and_resume_starts_new_anchor_with_committed_baseline() -> None:
    store, _ = build_active_job_history()
    commit(
        store,
        "root",
        "pause",
        8,
        [
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 4, "total": 10},
                },
            ),
            (JOB_PAUSED, {"job_id": "job"}),
        ],
    )
    paused = branch_state(store)
    assert derive_progress_anchors(paused, LogicalTime(8), branch_history(store)) == {}

    commit(store, "root", "resume", 12, [(JOB_ACTIVATED, {"job_id": "job"})])
    resumed = branch_state(store)

    assert derive_progress_anchors(resumed, LogicalTime(12), branch_history(store)) == {
        JobId("job"): ProgressAnchor(JobId("job"), LinearProgress(4, 10), LogicalTime(12))
    }


def test_atomic_activation_and_progress_have_one_transition_boundary() -> None:
    store, transitions = build_active_job_history()
    # Replace the standalone activation with a fresh branch whose activation batch
    # lists progress first to prove Event order has no anchor semantics.
    fork_position = HistoryPosition(stable_id(BranchId, "root"), transitions[2].transition_ref)
    store.fork_branch(stable_id(BranchId, "child"), fork_position)
    commit(
        store,
        "child",
        "activate-progress",
        5,
        [
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 2, "total": 10},
                },
            ),
            (JOB_ACTIVATED, {"job_id": "job"}),
        ],
    )

    anchors = derive_progress_anchors(
        branch_state(store, "child"),
        LogicalTime(5),
        branch_history(store, "child"),
    )

    assert anchors[JobId("job")] == ProgressAnchor(
        JobId("job"), LinearProgress(2, 10), LogicalTime(5)
    )


def test_history_helper_rejects_incoherent_time_and_missing_activation() -> None:
    store, transitions = build_active_job_history()
    state = branch_state(store)

    with pytest.raises(SchedulerHistoryError, match="current_time"):
        derive_progress_anchors(state, LogicalTime(4), branch_history(store))
    with pytest.raises(SchedulerHistoryError, match="no visible activation"):
        derive_progress_anchors(state, LogicalTime(2), transitions[:3])
    with pytest.raises(SchedulerHistoryError, match="must not be empty"):
        derive_progress_anchors(
            SimulationState.empty(stable_id(BranchId, "root")), LogicalTime(0), ()
        )


class AnchorProjector:
    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> Sequence[ScheduledResolution[JobId]]:
        assert state.execution.jobs
        return [
            ScheduledResolution(
                anchor.anchor_time + LogicalDuration(10),
                "JOB_EXPECTED_COMPLETION",
                anchor.job_id,
            )
            for anchor in progress_anchors.values()
        ]


def projected_index(
    state: SimulationState,
    current_time: LogicalTime,
    history: Sequence[CommittedTransition],
) -> ScheduledResolutionIndex[JobId]:
    anchors = derive_progress_anchors(state, current_time, history)
    projected = AnchorProjector().project(state, current_time, anchors)
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    index.rebuild(current_time, projected)
    return index


def test_parent_and_child_rebuild_from_isolated_visible_history() -> None:
    store, transitions = build_active_job_history()
    root_id = stable_id(BranchId, "root")
    child_id = stable_id(BranchId, "child")
    store.fork_branch(child_id, HistoryPosition(root_id, transitions[-1].transition_ref))
    commit(
        store,
        "root",
        "progress",
        5,
        [
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 2, "total": 10},
                },
            )
        ],
    )

    parent = projected_index(branch_state(store), LogicalTime(5), branch_history(store))
    child = projected_index(
        branch_state(store, "child"),
        LogicalTime(3),
        branch_history(store, "child"),
    )

    assert parent.snapshot(LogicalTime(5))[0].logical_time == LogicalTime(15)
    assert child.snapshot(LogicalTime(3))[0].logical_time == LogicalTime(13)
    child.replace_source(LogicalTime(3), JobId("job"), [])
    assert parent.snapshot(LogicalTime(5)) != ()


class StaticCheckpointLoader:
    def __init__(self, checkpoint: StateCheckpoint) -> None:
        self.checkpoint = checkpoint

    def load_checkpoint(self, target: HistoryPosition, /) -> StateCheckpoint | None:
        return self.checkpoint


def test_checkpoint_replay_rebuilds_same_schedule_without_scheduler_state() -> None:
    store, transitions = build_active_job_history()
    root_id = stable_id(BranchId, "root")
    checkpoint_position = HistoryPosition(root_id, transitions[-1].transition_ref)
    checkpoint_state = replay_branch(store, checkpoint_position)
    checkpoint = StateCheckpoint(checkpoint_position, checkpoint_state)
    commit(
        store,
        "root",
        "unrelated",
        8,
        [(ENTITY_UPDATED, {"entity_id": "actor", "properties_after": {"awake": True}})],
    )
    target = store.head_position(root_id)

    checkpoint_replay = replay_branch(store, target, StaticCheckpointLoader(checkpoint))
    full_replay = replay_branch(store, target)
    history = store.read_visible_transitions(target)

    assert checkpoint_replay == full_replay
    assert projected_index(checkpoint_replay, LogicalTime(8), history).snapshot(
        LogicalTime(8)
    ) == projected_index(full_replay, LogicalTime(8), history).snapshot(LogicalTime(8))
    assert not hasattr(checkpoint.state, "scheduled_resolutions")
    assert all(
        event.event_type != "ScheduledResolution" for item in history for event in item.events
    )
