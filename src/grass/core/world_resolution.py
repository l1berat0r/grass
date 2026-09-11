# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic Job-resolution contracts, validation, and Event preparation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol

from grass.core._structured_data import StructuredValue
from grass.core.branches import HistoryPosition
from grass.core.events import (
    CauseRef,
    CommittedTransition,
    Event,
    EventToCommit,
    TransitionToCommit,
)
from grass.core.identifiers import CorrelationId, EventId, JobId, TransitionId
from grass.core.logical_time import LogicalDuration, LogicalTime
from grass.core.projections import ProjectionError, project_transition
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.references import TransitionRef
from grass.core.resolution_events import RESOLUTION_OUTCOME_RECORDED, ResolutionOutcome
from grass.core.scheduler import ScheduledResolution
from grass.core.state import SimulationState
from grass.core.world_definitions import WorldDefinition
from grass.core.world_effect_materialization import (
    WorldEffectMaterializationError,
    validate_world_effect_vocabulary,
    validate_world_effects,
    world_effects_event_specs,
)
from grass.core.world_effects import WorldEffect

EventSpec = tuple[str, Mapping[str, StructuredValue]]


class ResolutionValidationError(ValueError):
    """A candidate resolution violates the approved Slice 7 contracts."""


class DeterministicResolutionIntegrityError(RuntimeError):
    """A deterministic provider failed or returned an invalid proposal."""


@dataclass(frozen=True, slots=True)
class JobResolutionSubject:
    """All due scheduler candidates for one Job in a conflict component."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    job_id: JobId
    due_candidates: Sequence[ScheduledResolution[JobId]]

    def __post_init__(self) -> None:
        if type(self.job_id) is not JobId:
            raise TypeError("job_id must be a JobId")
        if not isinstance(self.due_candidates, Sequence):
            raise TypeError("due_candidates must be a sequence")
        candidates = tuple(self.due_candidates)
        if not candidates:
            raise ValueError("a Job resolution subject requires due candidates")
        if any(type(candidate) is not ScheduledResolution for candidate in candidates):
            raise TypeError("due_candidates must contain ScheduledResolution values")
        if any(candidate.source_ref != self.job_id for candidate in candidates):
            raise ValueError("due candidates must reference the subject Job")
        if any(candidate in candidates[:index] for index, candidate in enumerate(candidates)):
            raise ValueError("due_candidates must not contain duplicates")
        object.__setattr__(self, "due_candidates", candidates)


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """Engine-created immutable input for one coherent Job conflict component."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    base_history_position: HistoryPosition
    target_logical_time: LogicalTime
    elapsed: LogicalDuration
    subjects: Sequence[JobResolutionSubject]
    state: SimulationState

    def __post_init__(self) -> None:
        if type(self.base_history_position) is not HistoryPosition:
            raise TypeError("base_history_position must be a HistoryPosition")
        if type(self.target_logical_time) is not LogicalTime:
            raise TypeError("target_logical_time must be a LogicalTime")
        if type(self.elapsed) is not LogicalDuration:
            raise TypeError("elapsed must be a LogicalDuration")
        if type(self.state) is not SimulationState:
            raise TypeError("state must be a SimulationState")
        if self.state.position.branch_id != self.base_history_position.branch_id:
            raise ValueError("request state and base history branches must match")
        local_ref = self.state.position.last_transition_ref
        base_ref = self.base_history_position.transition_ref
        if local_ref is not None and local_ref != base_ref:
            raise ValueError("request state does not match base history position")
        if (
            local_ref is None
            and base_ref is not None
            and base_ref.branch_id == self.base_history_position.branch_id
        ):
            raise ValueError("request state does not match local base history position")
        if self.elapsed.nanoseconds > self.target_logical_time.nanoseconds_from_origin:
            raise ValueError("elapsed cannot begin before the logical origin")
        if self.state.position.logical_time is not None:
            expected_elapsed = self.target_logical_time - self.state.position.logical_time
            if self.elapsed != expected_elapsed:
                raise ValueError("elapsed must begin at the request state's current logical time")

        if not isinstance(self.subjects, Sequence):
            raise TypeError("subjects must be a sequence")
        subjects = tuple(self.subjects)
        if not subjects:
            raise ValueError("a ResolutionRequest requires at least one Job subject")
        if not all(type(subject) is JobResolutionSubject for subject in subjects):
            raise TypeError("subjects must contain JobResolutionSubject values")
        job_ids = tuple(subject.job_id for subject in subjects)
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("request Job subjects must be unique")
        if any(job_id not in self.state.execution.jobs for job_id in job_ids):
            raise ValueError("request subjects must reference existing Jobs")
        candidates: list[ScheduledResolution[JobId]] = []
        for subject in subjects:
            if any(
                candidate.logical_time != self.target_logical_time
                for candidate in subject.due_candidates
            ):
                raise ValueError("all due candidates must share target_logical_time")
            candidates.extend(subject.due_candidates)
        if any(candidate in candidates[:index] for index, candidate in enumerate(candidates)):
            raise ValueError("a due candidate may belong to only one request subject")
        object.__setattr__(self, "subjects", subjects)


@dataclass(frozen=True, slots=True)
class SubjectResolutionOutcome:
    job_id: JobId
    outcome: ResolutionOutcome

    def __post_init__(self) -> None:
        if type(self.job_id) is not JobId:
            raise TypeError("job_id must be a JobId")
        if type(self.outcome) is not ResolutionOutcome:
            raise TypeError("outcome must be a ResolutionOutcome")


@dataclass(frozen=True, slots=True)
class ResolutionProposal:
    """One deterministic candidate outcome/effect batch without Event authority."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    outcomes: Sequence[SubjectResolutionOutcome]
    effects: Sequence[WorldEffect] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outcomes, Sequence):
            raise TypeError("outcomes must be a sequence")
        if not isinstance(self.effects, Sequence):
            raise TypeError("effects must be a sequence")
        outcomes = tuple(self.outcomes)
        effects = validate_world_effects(self.effects)
        if not all(type(outcome) is SubjectResolutionOutcome for outcome in outcomes):
            raise TypeError("outcomes must contain SubjectResolutionOutcome values")
        job_ids = tuple(outcome.job_id for outcome in outcomes)
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("proposal outcomes must not contain duplicate Jobs")
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "effects", effects)


class WorldResolutionProvider(Protocol):
    """Replaceable pure deterministic candidate-resolution boundary."""

    def resolve(self, request: ResolutionRequest, /) -> ResolutionProposal:
        """Propose one complete outcome/effect batch without committing it."""

        ...


@dataclass(frozen=True, slots=True)
class PreparedResolution:
    """A validated transition coupled to the history head it was derived from."""

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


def _event_specs(
    request: ResolutionRequest,
    proposal: ResolutionProposal,
) -> tuple[EventSpec, ...]:
    outcomes = {outcome.job_id: outcome.outcome for outcome in proposal.outcomes}
    records: list[EventSpec] = [
        (
            RESOLUTION_OUTCOME_RECORDED,
            {"job_id": subject.job_id.value, "outcome": outcomes[subject.job_id].value},
        )
        for subject in request.subjects
    ]
    records.extend(world_effects_event_specs(proposal.effects))
    return tuple(records)


def _validate_vocabulary(proposal: ResolutionProposal, world_definition: WorldDefinition) -> None:
    try:
        validate_world_effect_vocabulary(proposal.effects, world_definition)
    except WorldEffectMaterializationError as error:
        raise ResolutionValidationError(str(error)) from error


def _candidate_transition(
    request: ResolutionRequest,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    specs: Sequence[EventSpec],
    provenance: Provenance,
    causation_refs: Sequence[CauseRef],
    correlation_id: CorrelationId | None,
) -> TransitionToCommit:
    return TransitionToCommit(
        transition_ref=transition_ref,
        logical_time=request.target_logical_time,
        events=tuple(
            EventToCommit(
                event_id=event_id,
                event_type=event_type,
                event_version=1,
                payload=payload,
                provenance=provenance,
                causation_refs=causation_refs,
                correlation_id=correlation_id,
            )
            for event_id, (event_type, payload) in zip(event_ids, specs, strict=True)
        ),
    )


def _project_candidate(request: ResolutionRequest, transition: TransitionToCommit) -> None:
    first_sequence = request.state.position.last_sequence + 1
    committed = CommittedTransition(
        tuple(
            Event(
                event_id=record.event_id,
                branch_id=transition.transition_ref.branch_id,
                sequence=first_sequence + index,
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
        project_transition(request.state, committed)
    except ProjectionError as error:
        raise ResolutionValidationError(str(error)) from error


def _validate_coverage(request: ResolutionRequest, proposal: ResolutionProposal) -> None:
    expected = {subject.job_id for subject in request.subjects}
    actual = {outcome.job_id for outcome in proposal.outcomes}
    if actual != expected:
        missing = sorted(job_id.value for job_id in expected - actual)
        extra = sorted(job_id.value for job_id in actual - expected)
        raise ResolutionValidationError(
            f"proposal outcomes do not match request subjects; missing={missing}, extra={extra}"
        )


def _validation_transition(
    request: ResolutionRequest,
    specs: tuple[EventSpec, ...],
) -> TransitionToCommit:
    return _candidate_transition(
        request,
        TransitionRef(request.base_history_position.branch_id, TransitionId("validation")),
        tuple(EventId(f"validation:{index}") for index in range(len(specs))),
        specs,
        Provenance("WORLD_RESOLVER"),
        (),
        None,
    )


def validate_resolution_proposal(
    request: ResolutionRequest,
    proposal: ResolutionProposal,
    world_definition: WorldDefinition,
    /,
) -> None:
    """Purely validate one complete proposal against current Slice 7 contracts."""

    if type(request) is not ResolutionRequest:
        raise TypeError("request must be a ResolutionRequest")
    if type(proposal) is not ResolutionProposal:
        raise ResolutionValidationError("provider must return a ResolutionProposal")
    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    _validate_coverage(request, proposal)
    _validate_vocabulary(proposal, world_definition)
    specs = _event_specs(request, proposal)
    _project_candidate(request, _validation_transition(request, specs))


def _event_ids(values: Sequence[EventId]) -> tuple[EventId, ...]:
    if not isinstance(values, Sequence):
        raise TypeError("event_ids must be a sequence")
    event_ids = tuple(values)
    if not all(type(event_id) is EventId for event_id in event_ids):
        raise TypeError("event_ids must contain only EventId values")
    if len(set(event_ids)) != len(event_ids):
        raise ResolutionValidationError("event_ids must be unique")
    return event_ids


def _validate_base_history(
    request: ResolutionRequest,
    base_history: Sequence[CommittedTransition],
) -> None:
    if not isinstance(base_history, Sequence):
        raise TypeError("base_history must be a sequence")
    history = tuple(base_history)
    if not history:
        raise ResolutionValidationError("Job resolution requires non-empty base history")
    if not all(type(transition) is CommittedTransition for transition in history):
        raise TypeError("base_history must contain CommittedTransition values")
    latest = history[-1]
    if latest.transition_ref != request.base_history_position.transition_ref:
        raise ResolutionValidationError("base_history does not end at base_history_position")
    if latest.logical_time + request.elapsed != request.target_logical_time:
        raise ResolutionValidationError(
            "elapsed must begin at the base history position's logical time"
        )


def prepare_deterministic_resolution(
    provider: WorldResolutionProvider,
    request: ResolutionRequest,
    world_definition: WorldDefinition,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    *,
    base_history: Sequence[CommittedTransition],
    resolver_source_ref: ProvenanceSourceRef | None = None,
    resolver_metadata: Mapping[str, StructuredValue] | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedResolution:
    """Resolve, fully validate, and prepare one transition without committing it."""

    if type(request) is not ResolutionRequest:
        raise TypeError("request must be a ResolutionRequest")
    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    if type(transition_ref) is not TransitionRef:
        raise TypeError("transition_ref must be a TransitionRef")
    if transition_ref.branch_id != request.base_history_position.branch_id:
        raise ResolutionValidationError("transition and request branches must match")
    _validate_base_history(request, base_history)
    ids = _event_ids(event_ids)
    provenance = Provenance(
        "WORLD_RESOLVER",
        resolver_source_ref,
        {} if resolver_metadata is None else resolver_metadata,
    )
    if not isinstance(causation_refs, Sequence):
        raise TypeError("causation_refs must be a sequence")
    causes = tuple(causation_refs)
    if correlation_id is not None and type(correlation_id) is not CorrelationId:
        raise TypeError("correlation_id must be a CorrelationId or None")

    try:
        proposal = provider.resolve(request)
    except Exception as error:
        raise DeterministicResolutionIntegrityError(
            "deterministic WorldResolutionProvider failed"
        ) from error
    try:
        validate_resolution_proposal(request, proposal, world_definition)
    except (ResolutionValidationError, TypeError, ValueError) as error:
        raise DeterministicResolutionIntegrityError(
            "deterministic WorldResolutionProvider returned an invalid proposal"
        ) from error

    specs = _event_specs(request, proposal)
    if len(ids) != len(specs):
        raise ResolutionValidationError(
            f"resolution requires exactly {len(specs)} EventId values, got {len(ids)}"
        )
    transition = _candidate_transition(
        request,
        transition_ref,
        ids,
        specs,
        provenance,
        causes,
        correlation_id,
    )
    return PreparedResolution(request.base_history_position, transition)
