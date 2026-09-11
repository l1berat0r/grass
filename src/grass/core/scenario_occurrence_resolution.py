# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic scenario-occurrence resolution and Event preparation."""

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
from grass.core.identifiers import BranchId, CorrelationId, EventId, TransitionId
from grass.core.logical_time import LogicalDuration, LogicalTime
from grass.core.projections import ProjectionError, project_transition
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.references import TransitionRef
from grass.core.scenario_events import (
    SCENARIO_OCCURRENCE_RESOLVED,
    scenario_occurrence_ref_payload,
)
from grass.core.scenario_occurrences import (
    ScenarioOccurrenceHistoryError,
    derive_resolved_scenario_occurrences,
    project_scenario_occurrences,
)
from grass.core.scheduler import ScheduledResolution
from grass.core.state import SimulationState
from grass.core.world_definitions import (
    AtTimeScenarioEventRule,
    ScenarioOccurrenceRef,
    WorldDefinition,
)
from grass.core.world_effect_materialization import (
    WorldEffectMaterializationError,
    validate_world_effect_vocabulary,
    validate_world_effects,
    world_effects_event_specs,
)
from grass.core.world_effects import WorldEffect

EventSpec = tuple[str, Mapping[str, StructuredValue]]


class ScenarioOccurrenceResolutionValidationError(ValueError):
    """A candidate occurrence resolution violates the Slice 9 contracts."""


class DeterministicScenarioOccurrenceResolutionIntegrityError(RuntimeError):
    """A deterministic occurrence resolver failed or returned invalid output."""


@dataclass(frozen=True, slots=True)
class ScenarioOccurrenceResolutionRequest:
    """Engine-created input for one exact due scenario occurrence."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    base_history_position: HistoryPosition
    target_logical_time: LogicalTime
    elapsed: LogicalDuration
    occurrence_ref: ScenarioOccurrenceRef
    rule: AtTimeScenarioEventRule
    due_candidate: ScheduledResolution[ScenarioOccurrenceRef]
    state: SimulationState

    def __post_init__(self) -> None:
        if type(self.base_history_position) is not HistoryPosition:
            raise TypeError("base_history_position must be a HistoryPosition")
        if type(self.target_logical_time) is not LogicalTime:
            raise TypeError("target_logical_time must be a LogicalTime")
        if type(self.elapsed) is not LogicalDuration:
            raise TypeError("elapsed must be a LogicalDuration")
        if type(self.occurrence_ref) is not ScenarioOccurrenceRef:
            raise TypeError("occurrence_ref must be a ScenarioOccurrenceRef")
        if type(self.rule) is not AtTimeScenarioEventRule:
            raise TypeError("rule must be an AtTimeScenarioEventRule")
        if type(self.due_candidate) is not ScheduledResolution:
            raise TypeError("due_candidate must be a ScheduledResolution")
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
            and (base_ref.branch_id == self.base_history_position.branch_id)
        ):
            raise ValueError("request state does not match local base history position")
        if self.elapsed.nanoseconds > self.target_logical_time.nanoseconds_from_origin:
            raise ValueError("elapsed cannot begin before the logical origin")
        if self.state.position.logical_time is not None:
            expected_elapsed = self.target_logical_time - self.state.position.logical_time
            if self.elapsed != expected_elapsed:
                raise ValueError("elapsed must begin at the request state's current logical time")
        if self.rule.rule_id != self.occurrence_ref.scenario_event_rule_ref.rule_id:
            raise ValueError("rule does not match occurrence_ref")
        if self.rule.logical_time != self.target_logical_time:
            raise ValueError("rule logical_time must equal target_logical_time")
        if self.due_candidate.source_ref != self.occurrence_ref:
            raise ValueError("due candidate must reference the occurrence")
        if self.due_candidate.logical_time != self.target_logical_time:
            raise ValueError("due candidate must share target_logical_time")
        if self.due_candidate.kind != "SCENARIO_EVENT":
            raise ValueError("due candidate kind must be SCENARIO_EVENT")


@dataclass(frozen=True, slots=True)
class ScenarioOccurrenceResolutionProposal:
    """A deterministic occurrence proposal containing only transient effects."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    effects: Sequence[WorldEffect] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "effects", validate_world_effects(self.effects))


class ScenarioOccurrenceResolutionProvider(Protocol):
    """Replaceable deterministic scenario-occurrence candidate boundary."""

    def resolve(
        self, request: ScenarioOccurrenceResolutionRequest, /
    ) -> ScenarioOccurrenceResolutionProposal:
        """Propose effects without creating Events or committing history."""

        ...


class ScenarioOccurrenceHistoryReader(Protocol):
    """Read canonical ancestry-visible history for one exact position."""

    def read_visible_transitions(
        self, position: HistoryPosition, /
    ) -> Sequence[CommittedTransition]: ...


@dataclass(frozen=True, slots=True)
class PreparedScenarioOccurrenceResolution:
    """A validated occurrence transition coupled to its derivation head."""

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
    request: ScenarioOccurrenceResolutionRequest,
    proposal: ScenarioOccurrenceResolutionProposal,
) -> tuple[EventSpec, ...]:
    return (
        (
            SCENARIO_OCCURRENCE_RESOLVED,
            {"occurrence_ref": scenario_occurrence_ref_payload(request.occurrence_ref)},
        ),
        *world_effects_event_specs(proposal.effects),
    )


def _candidate_transition(
    request: ScenarioOccurrenceResolutionRequest,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    specs: Sequence[EventSpec],
    provenance: Provenance,
    causation_refs: Sequence[CauseRef],
    correlation_id: CorrelationId | None,
) -> TransitionToCommit:
    return TransitionToCommit(
        transition_ref,
        request.target_logical_time,
        tuple(
            EventToCommit(
                event_id,
                event_type,
                1,
                payload,
                provenance,
                causation_refs,
                correlation_id,
            )
            for event_id, (event_type, payload) in zip(event_ids, specs, strict=True)
        ),
    )


def _project_candidate(
    request: ScenarioOccurrenceResolutionRequest, transition: TransitionToCommit
) -> None:
    first_sequence = request.state.position.last_sequence + 1
    committed = CommittedTransition(
        tuple(
            Event(
                record.event_id,
                transition.transition_ref.branch_id,
                first_sequence + index,
                transition.logical_time,
                transition.transition_ref.transition_id,
                record.event_type,
                record.event_version,
                record.payload,
                record.provenance,
                record.causation_refs,
                record.correlation_id,
            )
            for index, record in enumerate(transition.events)
        )
    )
    try:
        project_transition(request.state, committed)
    except ProjectionError as error:
        raise ScenarioOccurrenceResolutionValidationError(str(error)) from error


def _validation_transition(
    request: ScenarioOccurrenceResolutionRequest, specs: tuple[EventSpec, ...]
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


def validate_scenario_occurrence_resolution_proposal(
    request: ScenarioOccurrenceResolutionRequest,
    proposal: ScenarioOccurrenceResolutionProposal,
    world_definition: WorldDefinition,
    /,
) -> None:
    """Validate a complete occurrence proposal against current contracts."""

    if type(request) is not ScenarioOccurrenceResolutionRequest:
        raise TypeError("request must be a ScenarioOccurrenceResolutionRequest")
    if type(proposal) is not ScenarioOccurrenceResolutionProposal:
        raise ScenarioOccurrenceResolutionValidationError(
            "provider must return a ScenarioOccurrenceResolutionProposal"
        )
    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    _validate_request_definition(request, world_definition)
    try:
        validate_world_effect_vocabulary(proposal.effects, world_definition)
    except WorldEffectMaterializationError as error:
        raise ScenarioOccurrenceResolutionValidationError(str(error)) from error
    specs = _event_specs(request, proposal)
    _project_candidate(request, _validation_transition(request, specs))


def _event_ids(values: Sequence[EventId]) -> tuple[EventId, ...]:
    if not isinstance(values, Sequence):
        raise TypeError("event_ids must be a sequence")
    event_ids = tuple(values)
    if not all(type(event_id) is EventId for event_id in event_ids):
        raise TypeError("event_ids must contain only EventId values")
    if len(set(event_ids)) != len(event_ids):
        raise ScenarioOccurrenceResolutionValidationError("event_ids must be unique")
    return event_ids


def _validate_base_history(
    request: ScenarioOccurrenceResolutionRequest,
    world_definition: WorldDefinition,
    base_history: Sequence[CommittedTransition],
) -> tuple[CommittedTransition, ...]:
    if not isinstance(base_history, Sequence):
        raise TypeError("base_history must be a sequence")
    history = tuple(base_history)
    if not history or not all(type(item) is CommittedTransition for item in history):
        raise ScenarioOccurrenceResolutionValidationError(
            "scenario occurrence resolution requires valid non-empty base history"
        )
    last_sequence_by_branch: dict[BranchId, int] = {}
    closed_branches: set[BranchId] = set()
    active_branch: BranchId | None = None
    for transition in history:
        branch_id = transition.branch_id
        if branch_id != active_branch:
            if branch_id in closed_branches:
                raise ScenarioOccurrenceResolutionValidationError(
                    "base_history branch segments must not be interleaved"
                )
            if active_branch is not None:
                closed_branches.add(active_branch)
            if transition.events[0].sequence != 1:
                raise ScenarioOccurrenceResolutionValidationError(
                    "base_history must begin each branch segment at Event sequence 1"
                )
            active_branch = branch_id
        expected_sequence = last_sequence_by_branch.get(branch_id, 0) + 1
        if transition.events[0].sequence != expected_sequence:
            raise ScenarioOccurrenceResolutionValidationError(
                "base_history must contain contiguous Event sequences"
            )
        last_sequence_by_branch[branch_id] = transition.events[-1].sequence
    latest = history[-1]
    if latest.transition_ref != request.base_history_position.transition_ref:
        raise ScenarioOccurrenceResolutionValidationError(
            "base_history does not end at base_history_position"
        )
    if latest.logical_time + request.elapsed != request.target_logical_time:
        raise ScenarioOccurrenceResolutionValidationError(
            "elapsed must begin at the base history position's logical time"
        )
    _validate_request_definition(request, world_definition)
    try:
        projected = project_scenario_occurrences(world_definition, latest.logical_time, history)
        resolved = derive_resolved_scenario_occurrences(history)
    except ScenarioOccurrenceHistoryError as error:
        raise ScenarioOccurrenceResolutionValidationError(str(error)) from error
    if request.occurrence_ref in resolved or request.due_candidate not in projected:
        raise ScenarioOccurrenceResolutionValidationError(
            "scenario occurrence is not unresolved and scheduled at the base history position"
        )
    return history


def _validate_request_definition(
    request: ScenarioOccurrenceResolutionRequest,
    world_definition: WorldDefinition,
) -> None:
    rule_ref = request.occurrence_ref.scenario_event_rule_ref
    if rule_ref.world_definition_ref != world_definition.ref:
        raise ScenarioOccurrenceResolutionValidationError(
            "occurrence does not belong to the WorldDefinition"
        )
    defined_rule = world_definition.scenario_event_rule(rule_ref.rule_id)
    if defined_rule != request.rule:
        raise ScenarioOccurrenceResolutionValidationError(
            "request rule does not match the WorldDefinition"
        )


def prepare_deterministic_scenario_occurrence_resolution(
    provider: ScenarioOccurrenceResolutionProvider,
    request: ScenarioOccurrenceResolutionRequest,
    world_definition: WorldDefinition,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    *,
    history_reader: ScenarioOccurrenceHistoryReader,
    resolver_source_ref: ProvenanceSourceRef | None = None,
    resolver_metadata: Mapping[str, StructuredValue] | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedScenarioOccurrenceResolution:
    """Resolve, fully validate, and prepare one occurrence without committing it."""

    if type(request) is not ScenarioOccurrenceResolutionRequest:
        raise TypeError("request must be a ScenarioOccurrenceResolutionRequest")
    if type(world_definition) is not WorldDefinition:
        raise TypeError("world_definition must be a WorldDefinition")
    if type(transition_ref) is not TransitionRef:
        raise TypeError("transition_ref must be a TransitionRef")
    if transition_ref.branch_id != request.base_history_position.branch_id:
        raise ScenarioOccurrenceResolutionValidationError(
            "transition and request branches must match"
        )
    read_visible_transitions = getattr(history_reader, "read_visible_transitions", None)
    if not callable(read_visible_transitions):
        raise TypeError("history_reader must provide read_visible_transitions")
    base_history = read_visible_transitions(request.base_history_position)
    _validate_base_history(request, world_definition, base_history)
    ids = _event_ids(event_ids)
    provenance = Provenance(
        "WORLD_RESOLVER",
        resolver_source_ref,
        {} if resolver_metadata is None else resolver_metadata,
    )
    if not isinstance(causation_refs, Sequence):
        raise TypeError("causation_refs must be a sequence")
    causes = tuple(causation_refs)
    if not all(type(item) is CauseRef for item in causes):
        raise TypeError("causation_refs must contain CauseRef values")
    if correlation_id is not None and type(correlation_id) is not CorrelationId:
        raise TypeError("correlation_id must be a CorrelationId or None")

    try:
        proposal = provider.resolve(request)
    except Exception as error:
        raise DeterministicScenarioOccurrenceResolutionIntegrityError(
            "deterministic ScenarioOccurrenceResolutionProvider failed"
        ) from error
    try:
        validate_scenario_occurrence_resolution_proposal(request, proposal, world_definition)
    except (ScenarioOccurrenceResolutionValidationError, TypeError, ValueError) as error:
        raise DeterministicScenarioOccurrenceResolutionIntegrityError(
            "deterministic ScenarioOccurrenceResolutionProvider returned an invalid proposal"
        ) from error

    specs = _event_specs(request, proposal)
    if len(ids) != len(specs):
        raise ScenarioOccurrenceResolutionValidationError(
            f"scenario occurrence resolution requires exactly {len(specs)} EventId values, "
            f"got {len(ids)}"
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
    return PreparedScenarioOccurrenceResolution(request.base_history_position, transition)
