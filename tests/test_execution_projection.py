# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence

import pytest

from grass.core import (
    BinaryProgress,
    BranchId,
    CommittedTransition,
    EntityId,
    EventPayload,
    InMemoryEventStore,
    JobId,
    JobStatus,
    LinearProgress,
    PlanId,
    PlanRef,
    ProjectionError,
    Provenance,
    SimulationState,
    project_transition,
)
from grass.core.execution_events import (
    JOB_ACTIVATED,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_CREATED,
    JOB_FAILED,
    JOB_PAUSED,
    JOB_PROGRESS_UPDATED,
    PLAN_CREATED,
    PLAN_REPLACED,
    PLAN_REVISED,
)
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, transition_to_commit


def plan_snapshot(
    *,
    plan_id: str = "plan",
    version: int = 1,
    step_id: str = "step",
    primitive: str = "WAIT",
    replaces: EventPayload | None = None,
) -> EventPayload:
    return {
        "plan_id": plan_id,
        "version": version,
        "actor_id": "actor",
        "objective": "Complete objective",
        "steps": [
            {
                "step_id": step_id,
                "primitive": primitive,
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


def job_created(
    *,
    job_id: str = "job",
    plan_id: str = "plan",
    version: int = 1,
    step_id: str = "step",
    progress: EventPayload | None = None,
) -> tuple[str, EventPayload]:
    return (
        JOB_CREATED,
        {
            "job_id": job_id,
            "plan_step_ref": {
                "plan_ref": {"plan_id": plan_id, "version": version},
                "step_id": step_id,
            },
            "progress": (
                {"kind": "LINEAR", "completed": 0, "total": 10} if progress is None else progress
            ),
        },
    )


def commit(
    store: InMemoryEventStore,
    label: str,
    events: Sequence[tuple[str, EventPayload]],
    *,
    logical_time: int = 1,
    branch: str = "root",
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
                    provenance=Provenance("ACTOR"),
                )
                for index, (event_type, payload) in enumerate(events)
            ],
        )
    )


def actor_state() -> tuple[InMemoryEventStore, SimulationState]:
    store = rooted_store("root")
    created = commit(
        store,
        "actor",
        [
            (
                ENTITY_CREATED,
                {"entity_id": "actor", "entity_type": "Person", "properties": {}},
            )
        ],
        logical_time=0,
    )
    return store, project_transition(SimulationState.empty(BranchId("test:root")), created)


def add_plan(
    store: InMemoryEventStore,
    state: SimulationState,
    *,
    snapshot: EventPayload | None = None,
    event_type: str = PLAN_CREATED,
    label: str = "plan",
) -> SimulationState:
    transition = commit(
        store,
        label,
        [(event_type, {"plan": plan_snapshot() if snapshot is None else snapshot})],
        logical_time=state.position.logical_time.nanoseconds_from_origin + 1
        if state.position.logical_time is not None
        else 1,
    )
    return project_transition(state, transition)


def add_job(
    store: InMemoryEventStore, state: SimulationState, *, label: str = "job"
) -> SimulationState:
    transition = commit(
        store,
        label,
        [job_created()],
        logical_time=state.position.logical_time.nanoseconds_from_origin + 1
        if state.position.logical_time is not None
        else 1,
    )
    return project_transition(state, transition)


def test_plan_creation_and_revision_preserve_immutable_versions() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    revised = plan_snapshot(version=2, primitive="MOVE")

    state = add_plan(store, state, snapshot=revised, event_type=PLAN_REVISED, label="revise")

    first = state.execution.plans[PlanRef(PlanId("plan"), 1)]
    second = state.execution.plans[PlanRef(PlanId("plan"), 2)]
    assert first.steps[0].primitive == "WAIT"
    assert second.steps[0].primitive == "MOVE"
    assert first.recorded_at != second.recorded_at


def test_plan_actor_may_be_created_in_same_atomic_transition() -> None:
    store = rooted_store("root")
    transition = commit(
        store,
        "mixed",
        [
            (PLAN_CREATED, {"plan": plan_snapshot()}),
            (
                ENTITY_CREATED,
                {"entity_id": "actor", "entity_type": "Person", "properties": {}},
            ),
        ],
    )

    state = project_transition(SimulationState.empty(BranchId("test:root")), transition)

    assert state.execution.plans[PlanRef(PlanId("plan"), 1)].actor_id == EntityId("actor")


@pytest.mark.parametrize(
    "event_type,snapshot,message",
    [
        (PLAN_CREATED, plan_snapshot(version=2), "version 1"),
        (PLAN_REVISED, plan_snapshot(version=2), "existing Plan"),
        (
            PLAN_REPLACED,
            plan_snapshot(plan_id="new", replaces=None),
            "requires replaces_plan_ref",
        ),
    ],
)
def test_invalid_plan_operation_fails_atomically(
    event_type: str, snapshot: EventPayload, message: str
) -> None:
    store, state = actor_state()
    transition = commit(store, "invalid", [(event_type, {"plan": snapshot})])

    with pytest.raises(ProjectionError, match=message):
        project_transition(state, transition)
    assert state.execution.plans == {}


def test_plan_replacement_is_final_but_replacement_may_be_revised() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    replacement = plan_snapshot(
        plan_id="replacement",
        step_id="replacement-step",
        replaces={"plan_id": "plan", "version": 1},
    )
    state = add_plan(
        store,
        state,
        snapshot=replacement,
        event_type=PLAN_REPLACED,
        label="replace",
    )

    replacement_revision = plan_snapshot(
        plan_id="replacement",
        version=2,
        step_id="replacement-step",
        primitive="MOVE",
        replaces={"plan_id": "plan", "version": 1},
    )
    continued = add_plan(
        store,
        state,
        snapshot=replacement_revision,
        event_type=PLAN_REVISED,
        label="replacement-revision",
    )
    assert PlanRef(PlanId("replacement"), 2) in continued.execution.plans

    old_revision = commit(
        store,
        "old-revision",
        [(PLAN_REVISED, {"plan": plan_snapshot(version=2)})],
        logical_time=4,
    )
    with pytest.raises(ProjectionError, match="replaced Plan"):
        project_transition(continued, old_revision)


def test_plan_replacement_must_target_latest_preexisting_version() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_plan(
        store,
        state,
        snapshot=plan_snapshot(version=2),
        event_type=PLAN_REVISED,
        label="revision",
    )
    replacement = plan_snapshot(
        plan_id="new",
        step_id="new-step",
        replaces={"plan_id": "plan", "version": 1},
    )
    transition = commit(
        store,
        "replace-old",
        [(PLAN_REPLACED, {"plan": replacement})],
        logical_time=3,
    )

    with pytest.raises(ProjectionError, match="latest pre-transition"):
        project_transition(state, transition)


def test_replacement_counts_as_operation_for_both_plan_ids() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    replacement = plan_snapshot(
        plan_id="new",
        step_id="new-step",
        replaces={"plan_id": "plan", "version": 1},
    )
    transition = commit(
        store,
        "conflict",
        [
            (PLAN_REPLACED, {"plan": replacement}),
            (PLAN_REVISED, {"plan": plan_snapshot(version=2)}),
        ],
        logical_time=2,
    )

    with pytest.raises(ProjectionError, match="one Plan operation"):
        project_transition(state, transition)


def test_job_may_reference_plan_created_in_same_transition() -> None:
    store, state = actor_state()
    transition = commit(
        store,
        "plan-and-job",
        [job_created(), (PLAN_CREATED, {"plan": plan_snapshot()})],
        logical_time=1,
    )

    state = project_transition(state, transition)
    job = state.execution.jobs[JobId("job")]

    assert job.status is JobStatus.PENDING
    assert job.progress == LinearProgress(0, 10)
    assert job.creation_provenance == Provenance("ACTOR")
    assert job.created_at == transition.logical_time


def test_plan_actor_must_exist_in_final_candidate_world() -> None:
    store = rooted_store("root")
    transition = commit(
        store,
        "missing-actor",
        [(PLAN_CREATED, {"plan": plan_snapshot()})],
    )

    with pytest.raises(ProjectionError, match="actors must reference existing"):
        project_transition(SimulationState.empty(BranchId("test:root")), transition)


def test_one_job_per_logical_step_across_plan_versions() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    state = add_plan(
        store,
        state,
        snapshot=plan_snapshot(version=2, primitive="MOVE"),
        event_type=PLAN_REVISED,
        label="revision",
    )
    second_job = job_created(job_id="second-job", version=2)
    transition = commit(store, "second-job", [second_job], logical_time=4)

    with pytest.raises(ProjectionError, match="at most one Job"):
        project_transition(state, transition)


def test_retry_uses_a_new_plan_step_and_job() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    state = project_transition(
        state,
        commit(store, "failure", [(JOB_FAILED, {"job_id": "job"})], logical_time=3),
    )
    state = add_plan(
        store,
        state,
        snapshot=plan_snapshot(version=2, step_id="retry-step"),
        event_type=PLAN_REVISED,
        label="retry-plan",
    )
    state = project_transition(
        state,
        commit(
            store,
            "retry-job",
            [job_created(job_id="retry-job", version=2, step_id="retry-step")],
            logical_time=5,
        ),
    )

    assert state.execution.jobs[JobId("job")].status is JobStatus.FAILED
    assert state.execution.jobs[JobId("retry-job")].status is JobStatus.PENDING


@pytest.mark.parametrize(
    "from_status,event_type,expected",
    [
        (JobStatus.PENDING, JOB_ACTIVATED, JobStatus.ACTIVE),
        (JobStatus.PENDING, JOB_FAILED, JobStatus.FAILED),
        (JobStatus.PENDING, JOB_CANCELLED, JobStatus.CANCELLED),
        (JobStatus.ACTIVE, JOB_PAUSED, JobStatus.PAUSED),
        (JobStatus.ACTIVE, JOB_FAILED, JobStatus.FAILED),
        (JobStatus.ACTIVE, JOB_CANCELLED, JobStatus.CANCELLED),
        (JobStatus.PAUSED, JOB_ACTIVATED, JobStatus.ACTIVE),
        (JobStatus.PAUSED, JOB_FAILED, JobStatus.FAILED),
        (JobStatus.PAUSED, JOB_CANCELLED, JobStatus.CANCELLED),
    ],
)
def test_legal_job_lifecycle_edges(
    from_status: JobStatus, event_type: str, expected: JobStatus
) -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    time = 3
    if from_status in (JobStatus.ACTIVE, JobStatus.PAUSED):
        state = project_transition(
            state,
            commit(store, "activate", [(JOB_ACTIVATED, {"job_id": "job"})], logical_time=time),
        )
        time += 1
    if from_status is JobStatus.PAUSED:
        state = project_transition(
            state,
            commit(store, "pause", [(JOB_PAUSED, {"job_id": "job"})], logical_time=time),
        )
        time += 1

    state = project_transition(
        state,
        commit(store, "target", [(event_type, {"job_id": "job"})], logical_time=time),
    )

    assert state.execution.jobs[JobId("job")].status is expected


@pytest.mark.parametrize(
    "from_status,event_type",
    [
        (JobStatus.PENDING, JOB_PAUSED),
        (JobStatus.ACTIVE, JOB_ACTIVATED),
        (JobStatus.PAUSED, JOB_PAUSED),
        (JobStatus.PAUSED, JOB_COMPLETED),
    ],
)
def test_illegal_job_lifecycle_edges_are_rejected(from_status: JobStatus, event_type: str) -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    time = 3
    if from_status in (JobStatus.ACTIVE, JobStatus.PAUSED):
        state = project_transition(
            state,
            commit(
                store,
                "activate",
                [(JOB_ACTIVATED, {"job_id": "job"})],
                logical_time=time,
            ),
        )
        time += 1
    if from_status is JobStatus.PAUSED:
        state = project_transition(
            state,
            commit(
                store,
                "pause",
                [(JOB_PAUSED, {"job_id": "job"})],
                logical_time=time,
            ),
        )
        time += 1
    transition = commit(
        store,
        "invalid-edge",
        [(event_type, {"job_id": "job"})],
        logical_time=time,
    )

    with pytest.raises(ProjectionError, match="invalid Job status transition"):
        project_transition(state, transition)


def test_combined_job_changes_are_order_independent() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    transition = commit(
        store,
        "instant",
        [
            (JOB_COMPLETED, {"job_id": "job"}),
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "BINARY", "complete": True},
                },
            ),
            job_created(progress={"kind": "BINARY", "complete": False}),
        ],
        logical_time=3,
    )

    state = project_transition(state, transition)

    assert state.execution.jobs[JobId("job")].status is JobStatus.COMPLETED
    assert state.execution.jobs[JobId("job")].progress == BinaryProgress(True)


def test_activation_may_atomically_include_progress() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    transition = commit(
        store,
        "activate-progress",
        [
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 3, "total": 10},
                },
            ),
            (JOB_ACTIVATED, {"job_id": "job"}),
        ],
        logical_time=3,
    )

    state = project_transition(state, transition)

    assert state.execution.jobs[JobId("job")].status is JobStatus.ACTIVE
    assert state.execution.jobs[JobId("job")].progress == LinearProgress(3, 10)


@pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.PAUSED])
def test_standalone_progress_requires_active_job(status: JobStatus) -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    time = 3
    if status is JobStatus.PAUSED:
        state = project_transition(
            state,
            commit(store, "activate", [(JOB_ACTIVATED, {"job_id": "job"})], logical_time=time),
        )
        state = project_transition(
            state,
            commit(store, "pause", [(JOB_PAUSED, {"job_id": "job"})], logical_time=time + 1),
        )
        time += 2
    update = commit(
        store,
        "progress",
        [
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 1, "total": 10},
                },
            )
        ],
        logical_time=time,
    )

    with pytest.raises(ProjectionError, match="requires active work"):
        project_transition(state, update)


def test_active_progress_may_combine_with_pause() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    state = project_transition(
        state,
        commit(store, "activate", [(JOB_ACTIVATED, {"job_id": "job"})], logical_time=3),
    )
    transition = commit(
        store,
        "progress-pause",
        [
            (JOB_PAUSED, {"job_id": "job"}),
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 4, "total": 10},
                },
            ),
        ],
        logical_time=4,
    )

    state = project_transition(state, transition)

    assert state.execution.jobs[JobId("job")].status is JobStatus.PAUSED
    assert state.execution.jobs[JobId("job")].progress == LinearProgress(4, 10)


@pytest.mark.parametrize(
    "progress",
    [
        {"kind": "LINEAR", "completed": 2, "total": 20},
        {"kind": "LINEAR", "completed": 0, "total": 10},
        {"kind": "BINARY", "complete": False},
    ],
)
def test_progress_model_total_and_completed_are_monotonic(progress: EventPayload) -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    state = project_transition(
        state,
        commit(
            store,
            "activate-progress",
            [
                (JOB_ACTIVATED, {"job_id": "job"}),
                (
                    JOB_PROGRESS_UPDATED,
                    {
                        "job_id": "job",
                        "progress_after": {
                            "kind": "LINEAR",
                            "completed": 3,
                            "total": 10,
                        },
                    },
                ),
            ],
            logical_time=3,
        ),
    )
    transition = commit(
        store,
        "invalid-progress",
        [(JOB_PROGRESS_UPDATED, {"job_id": "job", "progress_after": progress})],
        logical_time=4,
    )

    with pytest.raises(ProjectionError, match="monotonically"):
        project_transition(state, transition)


def test_linear_total_immutability_uses_numeric_equality() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    transition = commit(
        store,
        "activate-progress",
        [
            (JOB_ACTIVATED, {"job_id": "job"}),
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 1.0, "total": 10.0},
                },
            ),
        ],
        logical_time=3,
    )

    state = project_transition(state, transition)

    assert state.execution.jobs[JobId("job")].progress == LinearProgress(1.0, 10.0)


def test_completion_requires_terminal_progress_and_terminal_jobs_cannot_change() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    state = project_transition(
        state,
        commit(store, "activate", [(JOB_ACTIVATED, {"job_id": "job"})], logical_time=3),
    )
    incomplete = commit(
        store,
        "incomplete",
        [(JOB_COMPLETED, {"job_id": "job"})],
        logical_time=4,
    )
    with pytest.raises(ProjectionError, match="terminal progress"):
        project_transition(state, incomplete)

    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    state = project_transition(
        state,
        commit(store, "activate", [(JOB_ACTIVATED, {"job_id": "job"})], logical_time=3),
    )
    completed = commit(
        store,
        "complete",
        [
            (JOB_COMPLETED, {"job_id": "job"}),
            (
                JOB_PROGRESS_UPDATED,
                {
                    "job_id": "job",
                    "progress_after": {"kind": "LINEAR", "completed": 10, "total": 10},
                },
            ),
        ],
        logical_time=4,
    )
    state = project_transition(state, completed)
    later = commit(
        store,
        "later",
        [(JOB_FAILED, {"job_id": "job"})],
        logical_time=5,
    )
    with pytest.raises(ProjectionError, match="terminal Job"):
        project_transition(state, later)


def test_duplicate_job_change_dimensions_are_rejected() -> None:
    store, state = actor_state()
    state = add_plan(store, state)
    state = add_job(store, state)
    transition = commit(
        store,
        "duplicate",
        [
            (JOB_ACTIVATED, {"job_id": "job"}),
            (JOB_FAILED, {"job_id": "job"}),
        ],
        logical_time=3,
    )

    with pytest.raises(ProjectionError, match="one lifecycle"):
        project_transition(state, transition)
