# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Sequence

import pytest

from grass.core.branches import HistoryPosition
from grass.core.event_store import InMemoryEventStore, StaleHistoryError
from grass.core.events import EventPayload, EventToCommit
from grass.core.execution import (
    BinaryProgress,
    LinearProgress,
    PlanRef,
    PlanStepRef,
)
from grass.core.execution_commands import (
    JobStartValidationError,
    PreparedJobStartTransition,
    prepare_job_start_transition,
)
from grass.core.execution_events import JOB_ACTIVATED, JOB_CREATED, PLAN_CREATED, PLAN_REVISED
from grass.core.identifiers import (
    BranchId,
    EventId,
    JobId,
    PlanId,
    PlanStepId,
    TransitionId,
)
from grass.core.provenance import Provenance
from grass.core.references import TransitionRef
from grass.core.replay import replay_branch
from grass.core.state import SimulationState
from grass.core.world_events import ENTITY_CREATED
from tests.support import event_to_commit, rooted_store, stable_id, transition_to_commit


def _plan_snapshot(*, version: int = 1, primitive: str = "WAIT") -> EventPayload:
    return {
        "plan_id": "plan",
        "version": version,
        "actor_id": "actor",
        "objective": "Wait",
        "steps": [
            {
                "step_id": "step",
                "primitive": primitive,
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


def _commit(
    store: InMemoryEventStore,
    label: str,
    logical_time: int,
    events: Sequence[EventToCommit],
    *,
    branch: str = "root",
) -> None:
    store.commit_transition(transition_to_commit(branch, label, logical_time, events))


def _setup() -> tuple[InMemoryEventStore, SimulationState]:
    store = rooted_store("root")
    _commit(
        store,
        "setup",
        7,
        (
            event_to_commit(
                "actor",
                event_type=ENTITY_CREATED,
                payload={"entity_id": "actor", "entity_type": "Person", "properties": {}},
            ),
            event_to_commit(
                "plan",
                event_type=PLAN_CREATED,
                payload={"plan": _plan_snapshot()},
                provenance=Provenance("ACTOR"),
            ),
        ),
    )
    branch_id = stable_id(BranchId, "root")
    return store, replay_branch(store, store.head_position(branch_id))


def _prepare(
    store: InMemoryEventStore,
    state: SimulationState,
    *,
    plan_step_ref: PlanStepRef | None = None,
    job_id: JobId | None = None,
    progress: LinearProgress | BinaryProgress | None = None,
    event_ids: Sequence[EventId] | None = None,
    activate: bool = False,
) -> PreparedJobStartTransition:
    branch_id = state.position.branch_id
    return prepare_job_start_transition(
        state,
        PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("step"))
        if plan_step_ref is None
        else plan_step_ref,
        JobId("job") if job_id is None else job_id,
        BinaryProgress(False) if progress is None else progress,
        TransitionRef(branch_id, TransitionId("start")),
        (EventId("job-created"),) if event_ids is None else event_ids,
        base_history=store.read_visible_transitions(store.head_position(branch_id)),
        activate=activate,
    )


def test_prepares_pending_job_at_visible_head_and_commits_with_expected_head() -> None:
    store, state = _setup()

    prepared = _prepare(store, state, progress=LinearProgress(0, 12))

    assert prepared.expected_head == store.head_position(state.position.branch_id)
    assert prepared.transition.logical_time.nanoseconds_from_origin == 7
    assert [event.event_type for event in prepared.transition.events] == [JOB_CREATED]
    assert prepared.transition.events[0].payload == {
        "job_id": "job",
        "plan_step_ref": {
            "plan_ref": {"plan_id": "plan", "version": 1},
            "step_id": "step",
        },
        "progress": {"kind": "LINEAR", "completed": 0, "total": 12},
    }
    committed = store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    projected = replay_branch(store, store.head_position(state.position.branch_id))
    assert projected.execution.jobs[JobId("job")].created_at == committed.logical_time
    assert projected.execution.jobs[JobId("job")].status.value == "PENDING"


def test_optional_activation_is_atomic_and_requires_two_exact_event_ids() -> None:
    store, state = _setup()

    prepared = _prepare(
        store,
        state,
        activate=True,
        event_ids=(EventId("created"), EventId("activated")),
    )

    assert [event.event_type for event in prepared.transition.events] == [
        JOB_CREATED,
        JOB_ACTIVATED,
    ]
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    projected = replay_branch(store, store.head_position(state.position.branch_id))
    assert projected.execution.jobs[JobId("job")].status.value == "ACTIVE"

    second_store, second_state = _setup()
    with pytest.raises(JobStartValidationError, match="exactly 2"):
        _prepare(second_store, second_state, activate=True)


@pytest.mark.parametrize(
    "plan_step_ref,message",
    [
        (PlanStepRef(PlanRef(PlanId("missing"), 1), PlanStepId("step")), "exact Plan"),
        (PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("missing")), "exact PlanStep"),
    ],
)
def test_requires_exact_existing_plan_step(plan_step_ref: PlanStepRef, message: str) -> None:
    store, state = _setup()

    with pytest.raises(JobStartValidationError, match=message):
        _prepare(store, state, plan_step_ref=plan_step_ref)


@pytest.mark.parametrize(
    "progress",
    [LinearProgress(1, 2), BinaryProgress(True)],
)
def test_requires_initial_progress(progress: LinearProgress | BinaryProgress) -> None:
    store, state = _setup()

    with pytest.raises(JobStartValidationError, match="initial progress"):
        _prepare(store, state, progress=progress)


def test_rejects_duplicate_event_ids_and_existing_job_for_logical_step() -> None:
    store, state = _setup()
    with pytest.raises(JobStartValidationError, match="unique"):
        _prepare(
            store,
            state,
            activate=True,
            event_ids=(EventId("same"), EventId("same")),
        )

    prepared = _prepare(store, state)
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
    state = replay_branch(store, store.head_position(state.position.branch_id))
    _commit(
        store,
        "revision",
        8,
        (
            event_to_commit(
                "revision-event",
                event_type=PLAN_REVISED,
                payload={"plan": _plan_snapshot(version=2, primitive="MOVE")},
            ),
        ),
    )
    state = replay_branch(store, store.head_position(state.position.branch_id))

    with pytest.raises(JobStartValidationError, match="logical PlanStep"):
        _prepare(
            store,
            state,
            plan_step_ref=PlanStepRef(PlanRef(PlanId("plan"), 2), PlanStepId("step")),
            job_id=JobId("second-job"),
        )


def test_rejects_supplied_ids_already_present_in_visible_history() -> None:
    store, state = _setup()
    history = store.read_visible_transitions(store.head_position(state.position.branch_id))
    existing_event_id = history[0].events[0].event_id

    with pytest.raises(JobStartValidationError, match="event_id already exists"):
        prepare_job_start_transition(
            state,
            PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("step")),
            JobId("job"),
            BinaryProgress(False),
            TransitionRef(state.position.branch_id, TransitionId("start")),
            (existing_event_id,),
            base_history=history,
        )
    with pytest.raises(JobStartValidationError, match="transition_ref already exists"):
        prepare_job_start_transition(
            state,
            PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("step")),
            JobId("job"),
            BinaryProgress(False),
            history[0].transition_ref,
            (EventId("new-event"),),
            base_history=history,
        )


def test_rejects_branch_and_complete_history_misalignment() -> None:
    store, state = _setup()
    other_branch = stable_id(BranchId, "other")
    with pytest.raises(JobStartValidationError, match="branches"):
        prepare_job_start_transition(
            state,
            PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("step")),
            JobId("job"),
            BinaryProgress(False),
            TransitionRef(other_branch, TransitionId("start")),
            (EventId("event"),),
            base_history=store.read_visible_transitions(
                store.head_position(state.position.branch_id)
            ),
        )

    history = store.read_visible_transitions(store.head_position(state.position.branch_id))
    stale_state = SimulationState.empty(state.position.branch_id)
    with pytest.raises(JobStartValidationError, match="align"):
        prepare_job_start_transition(
            stale_state,
            PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("step")),
            JobId("job"),
            BinaryProgress(False),
            TransitionRef(stale_state.position.branch_id, TransitionId("start")),
            (EventId("event"),),
            base_history=history,
        )


def test_inherited_child_head_uses_visible_ancestor_time_and_child_expected_head() -> None:
    store, root_state = _setup()
    root_head = store.head_position(root_state.position.branch_id)
    child_id = stable_id(BranchId, "child")
    store.fork_branch(child_id, root_head)
    child_state = replay_branch(store, store.head_position(child_id))

    prepared = prepare_job_start_transition(
        child_state,
        PlanStepRef(PlanRef(PlanId("plan"), 1), PlanStepId("step")),
        JobId("child-job"),
        BinaryProgress(False),
        TransitionRef(child_id, TransitionId("start")),
        (EventId("child-event"),),
        base_history=store.read_visible_transitions(store.head_position(child_id)),
    )

    assert prepared.expected_head == HistoryPosition(child_id, root_head.transition_ref)
    assert prepared.transition.logical_time.nanoseconds_from_origin == 7
    store.commit_transition(prepared.transition, expected_head=prepared.expected_head)


def test_stale_expected_head_prevents_commit() -> None:
    store, state = _setup()
    prepared = _prepare(store, state)
    _commit(
        store,
        "intervening",
        7,
        (
            event_to_commit(
                "intervening-event",
                event_type=PLAN_REVISED,
                payload={"plan": _plan_snapshot(version=2)},
            ),
        ),
    )

    with pytest.raises(StaleHistoryError):
        store.commit_transition(prepared.transition, expected_head=prepared.expected_head)
