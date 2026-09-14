# SPDX-License-Identifier: GPL-3.0-only

"""Trusted preparation of authoritative execution command transitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from grass.core._structured_data import StructuredValue
from grass.core.branches import HistoryPosition
from grass.core.events import (
    CauseRef,
    CommittedTransition,
    Event,
    EventToCommit,
    TransitionToCommit,
)
from grass.core.execution import (
    BinaryProgress,
    JobProgress,
    LinearProgress,
    PlanStepRef,
)
from grass.core.execution import initial_progress as is_initial_progress
from grass.core.execution_events import JOB_ACTIVATED, JOB_CREATED
from grass.core.identifiers import (
    BranchId,
    CorrelationId,
    EventId,
    JobId,
)
from grass.core.projections import ProjectionError, project_transition
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.references import TransitionRef
from grass.core.state import ProjectionPosition, SimulationState


class JobStartValidationError(ValueError):
    """A requested Job start violates authoritative execution contracts."""


@dataclass(frozen=True, slots=True)
class PreparedJobStartTransition:
    """A validated Job-start transition coupled to its derivation head."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    expected_head: HistoryPosition
    transition: TransitionToCommit

    def __post_init__(self) -> None:
        if type(self.expected_head) is not HistoryPosition:
            raise TypeError("expected_head must be a HistoryPosition")
        if type(self.transition) is not TransitionToCommit:
            raise TypeError("transition must be a TransitionToCommit")
        if self.expected_head.branch_id != self.transition.transition_ref.branch_id:
            raise ValueError("expected_head and transition branches must match")


def _state_on_branch(state: SimulationState, branch_id: BranchId) -> SimulationState:
    return SimulationState(
        position=ProjectionPosition(branch_id),
        world=state.world,
        execution=state.execution,
        cognition=state.cognition,
    )


def _validate_base_history(
    state: SimulationState,
    base_history: Sequence[CommittedTransition],
) -> tuple[tuple[CommittedTransition, ...], HistoryPosition]:
    if not isinstance(base_history, Sequence):
        raise TypeError("base_history must be a sequence")
    history = tuple(base_history)
    if not history:
        raise JobStartValidationError("Job start requires non-empty base history")
    if not all(type(item) is CommittedTransition for item in history):
        raise TypeError("base_history must contain CommittedTransition values")

    transition_refs: set[TransitionRef] = set()
    event_ids: set[EventId] = set()
    closed_branches: set[BranchId] = set()
    active_branch: BranchId | None = None
    last_time = None
    projected: SimulationState | None = None
    for transition in history:
        if transition.transition_ref in transition_refs:
            raise JobStartValidationError("base_history contains a duplicate transition")
        transition_refs.add(transition.transition_ref)
        for event in transition.events:
            if event.event_id in event_ids:
                raise JobStartValidationError("base_history contains a duplicate EventId")
            event_ids.add(event.event_id)
        if last_time is not None and transition.logical_time < last_time:
            raise JobStartValidationError("base_history logical time must be nondecreasing")
        last_time = transition.logical_time

        branch_id = transition.branch_id
        if branch_id != active_branch:
            if branch_id in closed_branches:
                raise JobStartValidationError("base_history branch segments must not interleave")
            if active_branch is not None:
                closed_branches.add(active_branch)
            if transition.events[0].sequence != 1:
                raise JobStartValidationError(
                    "base_history must begin each branch segment at Event sequence 1"
                )
            active_branch = branch_id
            projected = (
                SimulationState.empty(branch_id)
                if projected is None
                else _state_on_branch(projected, branch_id)
            )
        if projected is None:  # pragma: no cover - history is non-empty
            raise AssertionError("missing projected state")
        try:
            projected = project_transition(projected, transition)
        except ProjectionError as error:
            raise JobStartValidationError(f"base_history is not projectable: {error}") from error

    if projected is None:  # pragma: no cover - history is non-empty
        raise AssertionError("missing projected state")
    target_branch = state.position.branch_id
    if projected.position.branch_id != target_branch:
        if any(transition.branch_id == target_branch for transition in history):
            raise JobStartValidationError("base_history does not end on the state branch")
        projected = _state_on_branch(projected, target_branch)
    if projected != state:
        raise JobStartValidationError("base_history does not align with the projected state")

    latest = history[-1]
    return history, HistoryPosition(target_branch, latest.transition_ref)


def _progress_payload(progress: JobProgress) -> Mapping[str, StructuredValue]:
    if type(progress) is LinearProgress:
        return {
            "kind": "LINEAR",
            "completed": progress.completed,
            "total": progress.total,
        }
    if type(progress) is BinaryProgress:
        return {"kind": "BINARY", "complete": progress.complete}
    raise TypeError("initial_progress must be LinearProgress or BinaryProgress")


def _event_ids(values: Sequence[EventId], expected_count: int) -> tuple[EventId, ...]:
    if not isinstance(values, Sequence):
        raise TypeError("event_ids must be a sequence")
    event_ids = tuple(values)
    if not all(type(event_id) is EventId for event_id in event_ids):
        raise TypeError("event_ids must contain EventId values")
    if len(set(event_ids)) != len(event_ids):
        raise JobStartValidationError("event_ids must be unique")
    if len(event_ids) != expected_count:
        raise JobStartValidationError(
            f"Job start requires exactly {expected_count} EventId values, got {len(event_ids)}"
        )
    return event_ids


def _project_candidate(state: SimulationState, transition: TransitionToCommit) -> None:
    committed = CommittedTransition(
        tuple(
            Event(
                event_id=record.event_id,
                branch_id=transition.transition_ref.branch_id,
                sequence=state.position.last_sequence + index + 1,
                logical_time=transition.logical_time,
                transition_id=transition.transition_ref.transition_id,
                event_type=record.event_type,
                event_version=record.event_version,
                payload=record.payload,
                provenance=record.provenance,
                causation_refs=record.causation_refs,
                correlation_id=record.correlation_id,
            )
            for index, record in enumerate(transition.events)
        )
    )
    try:
        project_transition(state, committed)
    except ProjectionError as error:
        raise JobStartValidationError(str(error)) from error


def prepare_job_start_transition(
    state: SimulationState,
    plan_step_ref: PlanStepRef,
    job_id: JobId,
    initial_progress: JobProgress,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    *,
    base_history: Sequence[CommittedTransition],
    activate: bool = False,
    start_source_ref: ProvenanceSourceRef | None = None,
    start_metadata: Mapping[str, StructuredValue] | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedJobStartTransition:
    """Validate and prepare one exact PlanStep start without selecting readiness."""

    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")
    if type(plan_step_ref) is not PlanStepRef:
        raise TypeError("plan_step_ref must be a PlanStepRef")
    if type(job_id) is not JobId:
        raise TypeError("job_id must be a JobId")
    if type(initial_progress) not in (LinearProgress, BinaryProgress):
        raise TypeError("initial_progress must be LinearProgress or BinaryProgress")
    if type(transition_ref) is not TransitionRef:
        raise TypeError("transition_ref must be a TransitionRef")
    if type(activate) is not bool:
        raise TypeError("activate must be a boolean")
    if transition_ref.branch_id != state.position.branch_id:
        raise JobStartValidationError("transition and state branches must match")
    if start_source_ref is not None and type(start_source_ref) is not ProvenanceSourceRef:
        raise TypeError("start_source_ref must be a ProvenanceSourceRef or None")
    if start_metadata is not None and not isinstance(start_metadata, Mapping):
        raise TypeError("start_metadata must be a mapping or None")
    if not isinstance(causation_refs, Sequence):
        raise TypeError("causation_refs must be a sequence")
    causes = tuple(causation_refs)
    if not all(type(item) is CauseRef for item in causes):
        raise TypeError("causation_refs must contain CauseRef values")
    if correlation_id is not None and type(correlation_id) is not CorrelationId:
        raise TypeError("correlation_id must be a CorrelationId or None")

    history, expected_head = _validate_base_history(state, base_history)
    if state.execution.plans.get(plan_step_ref.plan_ref) is None:
        raise JobStartValidationError("exact Plan does not exist")
    plan = state.execution.plans[plan_step_ref.plan_ref]
    if plan.step(plan_step_ref.step_id) is None:
        raise JobStartValidationError("exact PlanStep does not exist")
    if job_id in state.execution.jobs:
        raise JobStartValidationError("JobId already exists")
    if any(
        job.plan_step_ref.step_id == plan_step_ref.step_id for job in state.execution.jobs.values()
    ):
        raise JobStartValidationError("logical PlanStep already has a Job")
    if not is_initial_progress(initial_progress):
        raise JobStartValidationError("Job start requires initial progress")

    ids = _event_ids(event_ids, 2 if activate else 1)
    if any(transition.transition_ref == transition_ref for transition in history):
        raise JobStartValidationError("transition_ref already exists in visible history")
    visible_event_ids = {event.event_id for transition in history for event in transition.events}
    if any(event_id in visible_event_ids for event_id in ids):
        raise JobStartValidationError("event_id already exists in visible history")
    provenance = Provenance(
        "ENGINE",
        start_source_ref,
        {} if start_metadata is None else start_metadata,
    )
    records: list[tuple[str, Mapping[str, StructuredValue]]] = [
        (
            JOB_CREATED,
            {
                "job_id": job_id.value,
                "plan_step_ref": {
                    "plan_ref": {
                        "plan_id": plan_step_ref.plan_ref.plan_id.value,
                        "version": plan_step_ref.plan_ref.version,
                    },
                    "step_id": plan_step_ref.step_id.value,
                },
                "progress": _progress_payload(initial_progress),
            },
        )
    ]
    if activate:
        records.append((JOB_ACTIVATED, {"job_id": job_id.value}))
    transition = TransitionToCommit(
        transition_ref=transition_ref,
        logical_time=history[-1].logical_time,
        events=tuple(
            EventToCommit(
                event_id=event_id,
                event_type=event_type,
                event_version=1,
                payload=payload,
                provenance=provenance,
                causation_refs=causes,
                correlation_id=correlation_id,
            )
            for event_id, (event_type, payload) in zip(ids, records, strict=True)
        ),
    )
    _project_candidate(state, transition)
    return PreparedJobStartTransition(expected_head, transition)
