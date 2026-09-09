# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from grass.core import (
    BranchId,
    CommittedTransition,
    EventPayload,
    InMemoryEventStore,
    JobId,
    LogicalDuration,
    LogicalTime,
    ProgressAnchor,
    ScheduledResolution,
    ScheduledResolutionIndex,
    SchedulerStep,
    SimulationState,
    derive_progress_anchors,
    replay_branch,
)
from grass.core._structured_data import StructuredValue
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_COMPLETED,
    JOB_CREATED,
    JOB_PROGRESS_UPDATED,
    PLAN_CREATED,
)
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def plan_snapshot() -> EventPayload:
    steps: list[StructuredValue] = []
    for step_id in ("first-step", "second-step"):
        step: dict[str, StructuredValue] = {
            "step_id": step_id,
            "primitive": "WAIT",
            "blueprint_ref": None,
            "bindings": {},
            "parameters": {},
            "dependencies": [],
            "origin": "ACTOR_INTENT",
            "description": None,
        }
        steps.append(step)
    return {
        "plan_id": "plan",
        "version": 1,
        "actor_id": "actor",
        "objective": "Complete both jobs",
        "steps": steps,
        "replaces_plan_ref": None,
    }


def commit(
    store: InMemoryEventStore,
    label: str,
    logical_time: int,
    events: Sequence[tuple[str, EventPayload]],
) -> CommittedTransition:
    return store.commit_transition(
        transition_to_commit(
            "root",
            label,
            logical_time,
            [
                event_to_commit(
                    f"root:{label}:{index}",
                    event_type=event_type,
                    payload=payload,
                )
                for index, (event_type, payload) in enumerate(events)
            ],
        )
    )


def build_run() -> InMemoryEventStore:
    store = rooted_store("root")
    commit(
        store,
        "entity",
        0,
        [
            (
                ENTITY_CREATED,
                {"entity_id": "actor", "entity_type": "Person", "properties": {}},
            )
        ],
    )
    commit(store, "plan", 1, [(PLAN_CREATED, {"plan": plan_snapshot()})])
    commit(
        store,
        "jobs",
        2,
        [
            (
                JOB_CREATED,
                {
                    "job_id": job_id,
                    "plan_step_ref": {
                        "plan_ref": {"plan_id": "plan", "version": 1},
                        "step_id": step_id,
                    },
                    "progress": {"kind": "LINEAR", "completed": 0, "total": 10},
                },
            )
            for job_id, step_id in (
                ("first-job", "first-step"),
                ("second-job", "second-step"),
            )
        ],
    )
    commit(store, "activate-first", 3, [(JOB_ACTIVATED, {"job_id": "first-job"})])
    return store


class CompletionProjector:
    durations = {
        JobId("first-job"): LogicalDuration(5),
        JobId("second-job"): LogicalDuration(0),
    }

    def project(
        self,
        state: SimulationState,
        current_time: LogicalTime,
        progress_anchors: Mapping[JobId, ProgressAnchor],
        /,
    ) -> Sequence[ScheduledResolution[JobId]]:
        del state, current_time
        return [
            ScheduledResolution(
                anchor.anchor_time + self.durations[job_id],
                "JOB_EXPECTED_COMPLETION",
                job_id,
            )
            for job_id, anchor in progress_anchors.items()
        ]


def scheduler_inputs(
    store: InMemoryEventStore,
    projector: CompletionProjector,
) -> tuple[SimulationState, LogicalTime, Sequence[ScheduledResolution[JobId]]]:
    root_id = stable_id(BranchId, "root")
    position = store.head_position(root_id)
    history = store.read_visible_transitions(position)
    state = replay_branch(store, position)
    current_time = history[-1].logical_time
    anchors = derive_progress_anchors(state, current_time, history)
    return state, current_time, projector.project(state, current_time, anchors)


def candidate_keys(
    candidates: Sequence[ScheduledResolution[JobId]],
) -> set[tuple[int, str, JobId]]:
    return {
        (candidate.logical_time.nanoseconds_from_origin, candidate.kind, candidate.source_ref)
        for candidate in candidates
    }


def materialize_due_batch(
    store: InMemoryEventStore,
    step: SchedulerStep[JobId],
    transition_number: int,
) -> frozenset[JobId]:
    due_sources = sorted(
        (candidate.source_ref for candidate in step.due_candidates),
        key=lambda job_id: job_id.value,
    )
    events: list[tuple[str, EventPayload]] = []
    affected = set(due_sources)
    for job_id in due_sources:
        events.extend(
            [
                (
                    JOB_PROGRESS_UPDATED,
                    {
                        "job_id": job_id.value,
                        "progress_after": {
                            "kind": "LINEAR",
                            "completed": 10,
                            "total": 10,
                        },
                    },
                ),
                (JOB_COMPLETED, {"job_id": job_id.value}),
            ]
        )
        if job_id == JobId("first-job"):
            events.append((JOB_ACTIVATED, {"job_id": "second-job"}))
            affected.add(JobId("second-job"))
    commit(
        store,
        f"resolve-{transition_number}",
        step.target_time.nanoseconds_from_origin,
        events,
    )
    return frozenset(affected)


@dataclass(frozen=True)
class RunResult:
    history: tuple[CommittedTransition, ...]
    state: SimulationState
    elapsed: tuple[LogicalDuration, ...]


def run_scheduler(*, rebuild_after_every_commit: bool) -> RunResult:
    store = build_run()
    projector = CompletionProjector()
    _, current_time, projected = scheduler_inputs(store, projector)
    index: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
    index.rebuild(current_time, projected)
    elapsed: list[LogicalDuration] = []
    transition_number = 1

    while True:
        step = index.next_step(current_time, lambda _left, _right: False)
        if step is None:
            break
        elapsed.append(step.elapsed)
        affected = materialize_due_batch(store, step, transition_number)
        transition_number += 1
        _, current_time, projected = scheduler_inputs(store, projector)

        if rebuild_after_every_commit:
            index.rebuild(current_time, projected)
        else:
            for source_ref in sorted(affected, key=lambda job_id: job_id.value):
                index.replace_source(
                    current_time,
                    source_ref,
                    [candidate for candidate in projected if candidate.source_ref == source_ref],
                )
            rebuilt: ScheduledResolutionIndex[JobId] = ScheduledResolutionIndex()
            rebuilt.rebuild(current_time, projected)
            assert candidate_keys(index.snapshot(current_time)) == candidate_keys(
                rebuilt.snapshot(current_time)
            )

    root_id = stable_id(BranchId, "root")
    position = store.head_position(root_id)
    return RunResult(
        store.read_visible_transitions(position),
        replay_branch(store, position),
        tuple(elapsed),
    )


def test_incremental_and_rebuilt_scheduler_produce_identical_history() -> None:
    incremental = run_scheduler(rebuild_after_every_commit=False)
    rebuilt = run_scheduler(rebuild_after_every_commit=True)

    assert incremental.history == rebuilt.history
    assert incremental.state == rebuilt.state
    assert (
        incremental.elapsed
        == rebuilt.elapsed
        == (
            LogicalDuration(5),
            LogicalDuration(0),
        )
    )
    assert all(
        event.event_type != "ScheduledResolution"
        for transition in incremental.history
        for event in transition.events
    )
