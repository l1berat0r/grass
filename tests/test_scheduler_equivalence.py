# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from grass.core import (
    BranchId,
    CommittedTransition,
    EventId,
    EventPayload,
    InitialConditions,
    InMemoryEventStore,
    JobId,
    JobResolutionSubject,
    JobStatus,
    LinearProgress,
    LogicalDuration,
    LogicalTime,
    ProgressAnchor,
    ResolutionOutcome,
    ResolutionProposal,
    ResolutionRequest,
    ScheduledResolution,
    ScheduledResolutionIndex,
    SchedulerStep,
    SimulationState,
    SubjectResolutionOutcome,
    TransitionId,
    TransitionRef,
    UpdateJobEffect,
    WorldDefinition,
    WorldDefinitionId,
    WorldVocabulary,
    derive_progress_anchors,
    prepare_deterministic_resolution,
    replay_branch,
)
from grass.core._structured_data import StructuredValue
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_CREATED,
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


class CompletionResolver:
    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        outcomes = tuple(
            SubjectResolutionOutcome(subject.job_id, ResolutionOutcome.SUCCESS)
            for subject in request.subjects
        )
        effects: list[UpdateJobEffect] = []
        for subject in request.subjects:
            effects.append(
                UpdateJobEffect(
                    subject.job_id,
                    status_after=JobStatus.COMPLETED,
                    progress_after=LinearProgress(10, 10),
                )
            )
            if subject.job_id == JobId("first-job"):
                effects.append(UpdateJobEffect(JobId("second-job"), status_after=JobStatus.ACTIVE))
        return ResolutionProposal(outcomes, effects)


def resolution_definition() -> WorldDefinition:
    return WorldDefinition(
        WorldDefinitionId("scheduler-world"),
        "1.0",
        1,
        WorldVocabulary(entity_types=frozenset({"Person"})),
        InitialConditions(LogicalTime(0)),
    )


def materialize_due_batch(
    store: InMemoryEventStore,
    step: SchedulerStep[JobId],
    transition_number: int,
) -> frozenset[JobId]:
    assert len(step.conflict_components) == 1
    component = step.conflict_components[0]
    grouped: dict[JobId, list[ScheduledResolution[JobId]]] = {}
    for candidate in component:
        grouped.setdefault(candidate.source_ref, []).append(candidate)
    subjects = tuple(
        JobResolutionSubject(job_id, candidates)
        for job_id, candidates in sorted(grouped.items(), key=lambda item: item[0].value)
    )
    root_id = stable_id(BranchId, "root")
    base = store.head_position(root_id)
    state = replay_branch(store, base)
    request = ResolutionRequest(base, step.target_time, step.elapsed, subjects, state)
    effect_event_count = 2 * len(subjects) + (1 if JobId("first-job") in grouped else 0)
    event_count = len(subjects) + effect_event_count
    prepared = prepare_deterministic_resolution(
        CompletionResolver(),
        request,
        resolution_definition(),
        TransitionRef(root_id, stable_id(TransitionId, f"resolve-{transition_number}")),
        tuple(
            stable_id(EventId, f"root:resolve-{transition_number}:{index}")
            for index in range(event_count)
        ),
        base_history=store.read_visible_transitions(base),
    )
    store.commit_transition(
        prepared.transition,
        expected_head=prepared.expected_head,
    )
    affected = set(grouped)
    if JobId("first-job") in grouped:
        affected.add(JobId("second-job"))
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
