# SPDX-License-Identifier: GPL-3.0-only

"""Scripted trigger/provider boundaries and cognition transition preparation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Protocol, TypeAlias

from grass.core._structured_data import StructuredValue, freeze_structured_mapping
from grass.core.branches import HistoryPosition
from grass.core.cognition import (
    BoundedReaction,
    DecisionOutcomeKind,
    DecisionPoint,
    DecisionPointReason,
    DecisionPointScope,
    Observation,
    ProposedPlan,
)
from grass.core.cognition_events import (
    DECISION_POINT_CREATED,
    DECISION_RECORDED,
    OBSERVATION_CREATED,
)
from grass.core.events import (
    CauseRef,
    CommittedTransition,
    Event,
    EventToCommit,
    TransitionToCommit,
)
from grass.core.execution import Plan, PlanDependency, PlanRef, PlanStep
from grass.core.execution_events import PLAN_CREATED, PLAN_REPLACED, PLAN_REVISED
from grass.core.identifiers import (
    CorrelationId,
    DecisionPointId,
    EntityId,
    EventId,
    ObservationId,
)
from grass.core.logical_time import LogicalTime
from grass.core.projections import ProjectionError, project_transition
from grass.core.provenance import Provenance, ProvenanceSourceRef
from grass.core.references import TransitionRef
from grass.core.state import SimulationState


class CognitionValidationError(ValueError):
    """A requested cognition transition violates the Slice 8 contracts."""


class DecisionTriggerIntegrityError(RuntimeError):
    """A deterministic DecisionTriggerPolicy failed or returned invalid output."""


class DeterministicDecisionIntegrityError(RuntimeError):
    """A deterministic DecisionProvider failed or returned invalid output."""


class DecisionTriggerResult(StrEnum):
    CONTINUE = "CONTINUE"


@dataclass(frozen=True, slots=True)
class ObservationProposal:
    """Actor-relative content proposed for one Observation Event."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    observation_id: ObservationId
    actor_id: EntityId
    content: Mapping[str, StructuredValue]

    def __post_init__(self) -> None:
        if type(self.observation_id) is not ObservationId:
            raise TypeError("observation_id must be an ObservationId")
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        if not isinstance(self.content, Mapping):
            raise TypeError("content must be a mapping")
        object.__setattr__(
            self,
            "content",
            freeze_structured_mapping(self.content, description="ObservationProposal content"),
        )


@dataclass(frozen=True, slots=True)
class DecisionPointProposal:
    reason: DecisionPointReason
    scope: DecisionPointScope
    observation_ids: frozenset[ObservationId]
    subject_plan_ref: PlanRef | None = None

    def __post_init__(self) -> None:
        if type(self.reason) is not DecisionPointReason:
            raise TypeError("reason must be a DecisionPointReason")
        if type(self.scope) is not DecisionPointScope:
            raise TypeError("scope must be a DecisionPointScope")
        if type(self.observation_ids) is not frozenset or not all(
            type(item) is ObservationId for item in self.observation_ids
        ):
            raise TypeError("observation_ids must be a frozenset of ObservationId values")
        if self.subject_plan_ref is not None and type(self.subject_plan_ref) is not PlanRef:
            raise TypeError("subject_plan_ref must be a PlanRef or None")


@dataclass(frozen=True, slots=True)
class DecisionTriggerContext:
    observation: Observation
    subject_plan: Plan | None = None

    def __post_init__(self) -> None:
        if type(self.observation) is not Observation:
            raise TypeError("observation must be an Observation")
        if self.subject_plan is not None:
            if type(self.subject_plan) is not Plan:
                raise TypeError("subject_plan must be a Plan or None")
            if self.subject_plan.actor_id != self.observation.actor_id:
                raise ValueError("Observation and subject Plan must share one actor")


DecisionTriggerOutput: TypeAlias = DecisionTriggerResult | DecisionPointProposal


class DecisionTriggerPolicy(Protocol):
    def evaluate(self, context: DecisionTriggerContext, /) -> DecisionTriggerOutput:
        """Propose continuation or one DecisionPoint without committing it."""

        ...


class ScriptedDecisionTriggerPolicy:
    """Deterministic policy keyed by ObservationId for core tests and scenarios."""

    def __init__(self, scripts: Mapping[ObservationId, DecisionTriggerOutput]) -> None:
        values = dict(scripts)
        if not all(type(key) is ObservationId for key in values):
            raise TypeError("scripts must map ObservationId values")
        if not all(
            type(value) in (DecisionTriggerResult, DecisionPointProposal)
            for value in values.values()
        ):
            raise TypeError("scripts must contain supported trigger outputs")
        self._scripts = MappingProxyType(values)
        self._requests: list[DecisionTriggerContext] = []

    @property
    def requests(self) -> tuple[DecisionTriggerContext, ...]:
        return tuple(self._requests)

    def evaluate(self, context: DecisionTriggerContext, /) -> DecisionTriggerOutput:
        if type(context) is not DecisionTriggerContext:
            raise TypeError("context must be a DecisionTriggerContext")
        self._requests.append(context)
        try:
            return self._scripts[context.observation.observation_id]
        except KeyError as error:
            raise LookupError(
                f"no trigger script for {context.observation.observation_id}"
            ) from error


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """Narrow immutable actor-relative input for one pending DecisionPoint."""

    decision_point: DecisionPoint
    observations: Sequence[Observation]
    subject_plan: Plan | None

    def __post_init__(self) -> None:
        if type(self.decision_point) is not DecisionPoint:
            raise TypeError("decision_point must be a DecisionPoint")
        observations = tuple(self.observations)
        if not all(type(item) is Observation for item in observations):
            raise TypeError("observations must contain Observation values")
        if frozenset(item.observation_id for item in observations) != (
            self.decision_point.observation_ids
        ):
            raise ValueError("observations must exactly match the DecisionPoint references")
        if any(item.actor_id != self.decision_point.actor_id for item in observations):
            raise ValueError("DecisionRequest Observations must belong to the actor")
        if self.subject_plan is None:
            if self.decision_point.subject_plan_ref is not None:
                raise ValueError("DecisionRequest is missing its subject Plan")
        else:
            if type(self.subject_plan) is not Plan:
                raise TypeError("subject_plan must be a Plan or None")
            if self.subject_plan.ref != self.decision_point.subject_plan_ref:
                raise ValueError("DecisionRequest subject Plan does not match DecisionPoint")
            if self.subject_plan.actor_id != self.decision_point.actor_id:
                raise ValueError("DecisionRequest subject Plan must belong to the actor")
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True, slots=True)
class DecisionProposal:
    """Untrusted structured output from a DecisionProvider."""

    kind: DecisionOutcomeKind
    proposed_plan: ProposedPlan | None = None
    bounded_reaction: BoundedReaction | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not DecisionOutcomeKind:
            raise TypeError("kind must be a DecisionOutcomeKind")
        plan_required = self.kind in (
            DecisionOutcomeKind.REVISE_PLAN,
            DecisionOutcomeKind.REPLACE_PLAN,
        )
        if plan_required != (self.proposed_plan is not None):
            raise ValueError("Plan decisions require exactly one proposed Plan")
        if self.proposed_plan is not None and type(self.proposed_plan) is not ProposedPlan:
            raise TypeError("proposed_plan must be a ProposedPlan or None")
        reaction_required = self.kind is DecisionOutcomeKind.BOUNDED_REACTION
        if reaction_required != (self.bounded_reaction is not None):
            raise ValueError("BOUNDED_REACTION requires exactly one bounded reaction")
        if self.bounded_reaction is not None and type(self.bounded_reaction) is not BoundedReaction:
            raise TypeError("bounded_reaction must be a BoundedReaction or None")


class DecisionProvider(Protocol):
    def decide(self, request: DecisionRequest, /) -> DecisionProposal:
        """Propose one structured actor decision without committing it."""

        ...


class ScriptedDecisionProvider:
    """Deterministic DecisionProvider keyed by DecisionPointId."""

    def __init__(self, scripts: Mapping[DecisionPointId, DecisionProposal]) -> None:
        values = dict(scripts)
        if not all(type(key) is DecisionPointId for key in values):
            raise TypeError("scripts must map DecisionPointId values")
        if not all(type(value) is DecisionProposal for value in values.values()):
            raise TypeError("scripts must contain DecisionProposal values")
        self._scripts = MappingProxyType(values)
        self._requests: list[DecisionRequest] = []

    @property
    def requests(self) -> tuple[DecisionRequest, ...]:
        return tuple(self._requests)

    def decide(self, request: DecisionRequest, /) -> DecisionProposal:
        if type(request) is not DecisionRequest:
            raise TypeError("request must be a DecisionRequest")
        self._requests.append(request)
        try:
            return self._scripts[request.decision_point.decision_point_id]
        except KeyError as error:
            raise LookupError(
                f"no decision script for {request.decision_point.decision_point_id}"
            ) from error


@dataclass(frozen=True, slots=True)
class PreparedCognitionTransition:
    """A validated cognition transition coupled to its derivation head."""

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


EventSpec: TypeAlias = tuple[
    str,
    Mapping[str, StructuredValue],
    Provenance,
    tuple[CauseRef, ...],
]


def _plan_ref_payload(plan_ref: PlanRef | None) -> StructuredValue:
    if plan_ref is None:
        return None
    return {"plan_id": plan_ref.plan_id.value, "version": plan_ref.version}


def _dependencies_payload(dependencies: frozenset[PlanDependency]) -> list[StructuredValue]:
    return [
        {"step_id": dependency.step_id.value, "condition": dependency.condition.value}
        for dependency in sorted(
            dependencies,
            key=lambda item: (item.step_id.value, item.condition.value),
        )
    ]


def _step_payload(step: PlanStep) -> Mapping[str, StructuredValue]:
    blueprint_ref: StructuredValue = None
    if step.blueprint_ref is not None:
        blueprint_ref = {
            "blueprint_id": step.blueprint_ref.blueprint_id.value,
            "version": step.blueprint_ref.version,
        }
    return {
        "step_id": step.step_id.value,
        "primitive": step.primitive.value,
        "blueprint_ref": blueprint_ref,
        "bindings": step.bindings,
        "parameters": step.parameters,
        "dependencies": _dependencies_payload(step.dependencies),
        "origin": step.origin.value,
        "description": step.description,
    }


def _plan_payload(plan: Plan) -> Mapping[str, StructuredValue]:
    return {
        "plan": {
            "plan_id": plan.plan_id.value,
            "version": plan.version,
            "actor_id": plan.actor_id.value,
            "objective": plan.objective,
            "steps": [_step_payload(step) for step in plan.steps],
            "replaces_plan_ref": _plan_ref_payload(plan.replaces_plan_ref),
        }
    }


def _observation_payload(proposal: ObservationProposal) -> Mapping[str, StructuredValue]:
    return {
        "observation_id": proposal.observation_id.value,
        "actor_id": proposal.actor_id.value,
        "content": proposal.content,
    }


def _decision_point_payload(
    decision_point_id: DecisionPointId,
    actor_id: EntityId,
    proposal: DecisionPointProposal,
) -> Mapping[str, StructuredValue]:
    return {
        "decision_point_id": decision_point_id.value,
        "actor_id": actor_id.value,
        "reason": proposal.reason.value,
        "scope": proposal.scope.value,
        "observation_ids": [
            item.value for item in sorted(proposal.observation_ids, key=lambda item: item.value)
        ],
        "subject_plan_ref": _plan_ref_payload(proposal.subject_plan_ref),
    }


def _decision_payload(
    decision_point_id: DecisionPointId,
    proposal: DecisionProposal,
) -> Mapping[str, StructuredValue]:
    if proposal.kind is DecisionOutcomeKind.CONTINUE_PLAN:
        outcome: Mapping[str, StructuredValue] = {"kind": proposal.kind.value}
    elif proposal.kind is DecisionOutcomeKind.REVISE_PLAN:
        if proposal.proposed_plan is None:  # pragma: no cover - enforced by value contract
            raise AssertionError("missing proposed Plan")
        outcome = {
            "kind": proposal.kind.value,
            "resulting_plan_ref": _plan_ref_payload(proposal.proposed_plan.ref),
        }
    elif proposal.kind is DecisionOutcomeKind.REPLACE_PLAN:
        if proposal.proposed_plan is None:  # pragma: no cover - enforced by value contract
            raise AssertionError("missing proposed Plan")
        outcome = {
            "kind": proposal.kind.value,
            "resulting_plan_ref": _plan_ref_payload(proposal.proposed_plan.ref),
        }
    else:
        reaction = proposal.bounded_reaction
        if reaction is None:  # pragma: no cover - enforced by value contract
            raise AssertionError("missing bounded reaction")
        outcome = {
            "kind": proposal.kind.value,
            "bounded_reaction": {
                "intent_description": reaction.intent_description,
                "content": reaction.content,
            },
        }
    return {"decision_point_id": decision_point_id.value, "outcome": outcome}


def _validate_common(
    state: SimulationState,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    base_history: Sequence[CommittedTransition],
    causation_refs: Sequence[CauseRef],
    correlation_id: CorrelationId | None,
) -> tuple[tuple[EventId, ...], tuple[CauseRef, ...], HistoryPosition, LogicalTime]:
    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")
    if type(transition_ref) is not TransitionRef:
        raise TypeError("transition_ref must be a TransitionRef")
    if transition_ref.branch_id != state.position.branch_id:
        raise CognitionValidationError("transition and state branches must match")
    if not isinstance(event_ids, Sequence):
        raise TypeError("event_ids must be a sequence")
    ids = tuple(event_ids)
    if not all(type(item) is EventId for item in ids):
        raise TypeError("event_ids must contain EventId values")
    if len(set(ids)) != len(ids):
        raise CognitionValidationError("event_ids must be unique")
    if not isinstance(base_history, Sequence):
        raise TypeError("base_history must be a sequence")
    history = tuple(base_history)
    if not history:
        raise CognitionValidationError("cognition preparation requires non-empty base history")
    if not all(type(item) is CommittedTransition for item in history):
        raise TypeError("base_history must contain CommittedTransition values")
    latest = history[-1]
    if (
        state.position.last_transition_ref is not None
        and state.position.last_transition_ref != latest.transition_ref
    ):
        raise CognitionValidationError("base_history does not end at the projected state position")
    if not isinstance(causation_refs, Sequence):
        raise TypeError("causation_refs must be a sequence")
    causes = tuple(causation_refs)
    if not all(type(item) is CauseRef for item in causes):
        raise TypeError("causation_refs must contain CauseRef values")
    if correlation_id is not None and type(correlation_id) is not CorrelationId:
        raise TypeError("correlation_id must be a CorrelationId or None")
    return (
        ids,
        causes,
        HistoryPosition(state.position.branch_id, latest.transition_ref),
        latest.logical_time,
    )


def _candidate_transition(
    transition_ref: TransitionRef,
    logical_time: LogicalTime,
    event_ids: tuple[EventId, ...],
    specs: tuple[EventSpec, ...],
    correlation_id: CorrelationId | None,
) -> TransitionToCommit:
    if len(event_ids) != len(specs):
        raise CognitionValidationError(
            f"cognition transition requires exactly {len(specs)} EventId values, "
            f"got {len(event_ids)}"
        )
    return TransitionToCommit(
        transition_ref=transition_ref,
        logical_time=logical_time,
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
            for event_id, (event_type, payload, provenance, causes) in zip(
                event_ids, specs, strict=True
            )
        ),
    )


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
        raise CognitionValidationError(str(error)) from error


def prepare_observation_transition(
    policy: DecisionTriggerPolicy,
    state: SimulationState,
    observation: ObservationProposal,
    subject_plan_ref: PlanRef | None,
    decision_point_id: DecisionPointId | None,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    *,
    base_history: Sequence[CommittedTransition],
    perception_source_ref: ProvenanceSourceRef | None = None,
    perception_metadata: Mapping[str, StructuredValue] | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedCognitionTransition:
    """Prepare one Observation and its optional triggered DecisionPoint."""

    if type(observation) is not ObservationProposal:
        raise TypeError("observation must be an ObservationProposal")
    if subject_plan_ref is not None and type(subject_plan_ref) is not PlanRef:
        raise TypeError("subject_plan_ref must be a PlanRef or None")
    if decision_point_id is not None and type(decision_point_id) is not DecisionPointId:
        raise TypeError("decision_point_id must be a DecisionPointId or None")
    ids, source_causes, expected_head, logical_time = _validate_common(
        state,
        transition_ref,
        event_ids,
        base_history,
        causation_refs,
        correlation_id,
    )
    if not ids:
        raise CognitionValidationError("Observation transition requires EventId values")
    perception_provenance = Provenance(
        "PERCEPTION",
        perception_source_ref,
        {} if perception_metadata is None else perception_metadata,
    )
    projected_observation = Observation(
        observation.observation_id,
        observation.actor_id,
        observation.content,
        perception_provenance,
        logical_time,
    )
    subject_plan = None
    if subject_plan_ref is not None:
        subject_plan = state.execution.plans.get(subject_plan_ref)
        if subject_plan is None:
            raise CognitionValidationError("subject Plan does not exist")
    context = DecisionTriggerContext(projected_observation, subject_plan)
    try:
        output = policy.evaluate(context)
    except Exception as error:
        raise DecisionTriggerIntegrityError("deterministic DecisionTriggerPolicy failed") from error
    if type(output) not in (DecisionTriggerResult, DecisionPointProposal):
        raise DecisionTriggerIntegrityError(
            "deterministic DecisionTriggerPolicy returned invalid output"
        )
    if type(output) is DecisionPointProposal:
        available_observations = dict(state.cognition.observations)
        available_observations[projected_observation.observation_id] = projected_observation
        for observation_id in output.observation_ids:
            referenced = available_observations.get(observation_id)
            if referenced is None or referenced.actor_id != observation.actor_id:
                raise DecisionTriggerIntegrityError(
                    "DecisionPoint proposal references unavailable actor cognition"
                )

    specs: list[EventSpec] = [
        (
            OBSERVATION_CREATED,
            _observation_payload(observation),
            perception_provenance,
            source_causes,
        )
    ]
    if output is DecisionTriggerResult.CONTINUE:
        if decision_point_id is not None:
            raise CognitionValidationError("CONTINUE must not allocate a DecisionPointId")
    else:
        if decision_point_id is None:
            raise CognitionValidationError("triggered DecisionPoint requires a DecisionPointId")
        if output.subject_plan_ref != subject_plan_ref:
            raise DecisionTriggerIntegrityError(
                "DecisionPoint proposal changed the exact subject Plan"
            )
        specs.append(
            (
                DECISION_POINT_CREATED,
                _decision_point_payload(decision_point_id, observation.actor_id, output),
                Provenance("DECISION_TRIGGER"),
                (CauseRef("event", ids[0].value),),
            )
        )

    transition = _candidate_transition(
        transition_ref, logical_time, ids, tuple(specs), correlation_id
    )
    _project_candidate(state, transition)
    return PreparedCognitionTransition(expected_head, transition)


def prepare_decision_point_transition(
    state: SimulationState,
    actor_id: EntityId,
    decision_point_id: DecisionPointId,
    proposal: DecisionPointProposal,
    transition_ref: TransitionRef,
    event_id: EventId,
    *,
    base_history: Sequence[CommittedTransition],
    trigger_source_ref: ProvenanceSourceRef | None = None,
    trigger_metadata: Mapping[str, StructuredValue] | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedCognitionTransition:
    """Prepare one engine-triggered DecisionPoint without an Observation."""

    if type(actor_id) is not EntityId:
        raise TypeError("actor_id must be an EntityId")
    if type(decision_point_id) is not DecisionPointId:
        raise TypeError("decision_point_id must be a DecisionPointId")
    if type(proposal) is not DecisionPointProposal:
        raise TypeError("proposal must be a DecisionPointProposal")
    ids, causes, expected_head, logical_time = _validate_common(
        state,
        transition_ref,
        (event_id,),
        base_history,
        causation_refs,
        correlation_id,
    )
    if proposal.observation_ids:
        raise CognitionValidationError(
            "standalone DecisionPoint must not reference unprovided Observations"
        )
    provenance = Provenance(
        "DECISION_TRIGGER",
        trigger_source_ref,
        {} if trigger_metadata is None else trigger_metadata,
    )
    transition = _candidate_transition(
        transition_ref,
        logical_time,
        ids,
        (
            (
                DECISION_POINT_CREATED,
                _decision_point_payload(decision_point_id, actor_id, proposal),
                provenance,
                causes,
            ),
        ),
        correlation_id,
    )
    _project_candidate(state, transition)
    return PreparedCognitionTransition(expected_head, transition)


def build_decision_request(
    state: SimulationState, decision_point_id: DecisionPointId
) -> DecisionRequest:
    """Build the exact actor-relative request for one pending DecisionPoint."""

    if type(state) is not SimulationState:
        raise TypeError("state must be a SimulationState")
    if type(decision_point_id) is not DecisionPointId:
        raise TypeError("decision_point_id must be a DecisionPointId")
    point = state.cognition.decision_points.get(decision_point_id)
    if point is None:
        raise CognitionValidationError("DecisionPoint does not exist")
    if decision_point_id in state.cognition.decisions:
        raise CognitionValidationError("DecisionPoint is already resolved")
    observations = tuple(
        state.cognition.observations[item]
        for item in sorted(point.observation_ids, key=lambda item: item.value)
    )
    subject_plan = (
        None
        if point.subject_plan_ref is None
        else state.execution.plans.get(point.subject_plan_ref)
    )
    return DecisionRequest(point, observations, subject_plan)


def _materialized_plan(
    request: DecisionRequest,
    proposal: DecisionProposal,
    provenance: Provenance,
    recorded_at: LogicalTime,
) -> tuple[Plan, str] | None:
    candidate = proposal.proposed_plan
    subject = request.decision_point.subject_plan_ref
    if proposal.kind is DecisionOutcomeKind.CONTINUE_PLAN:
        if subject is None:
            raise CognitionValidationError("CONTINUE_PLAN requires subject_plan_ref")
        return None
    if proposal.kind is DecisionOutcomeKind.BOUNDED_REACTION:
        return None
    if candidate is None:  # pragma: no cover - enforced by DecisionProposal
        raise AssertionError("missing proposed Plan")
    if candidate.actor_id != request.decision_point.actor_id:
        raise CognitionValidationError("proposed Plan actor must match DecisionPoint")

    if proposal.kind is DecisionOutcomeKind.REVISE_PLAN:
        if subject is None:
            raise CognitionValidationError("REVISE_PLAN requires subject_plan_ref")
        if candidate.plan_id != subject.plan_id or candidate.version != subject.version + 1:
            raise CognitionValidationError(
                "REVISE_PLAN must propose the exact next subject Plan version"
            )
        event_type = PLAN_REVISED
    elif subject is None:
        if candidate.version != 1 or candidate.replaces_plan_ref is not None:
            raise CognitionValidationError(
                "initial REPLACE_PLAN requires version 1 and no replacement reference"
            )
        event_type = PLAN_CREATED
    else:
        if (
            candidate.plan_id == subject.plan_id
            or candidate.version != 1
            or candidate.replaces_plan_ref != subject
        ):
            raise CognitionValidationError(
                "REPLACE_PLAN must propose a new version-1 Plan replacing the exact subject"
            )
        event_type = PLAN_REPLACED

    return (
        Plan(
            plan_id=candidate.plan_id,
            version=candidate.version,
            actor_id=candidate.actor_id,
            objective=candidate.objective,
            steps=candidate.steps,
            replaces_plan_ref=candidate.replaces_plan_ref,
            provenance=provenance,
            recorded_at=recorded_at,
        ),
        event_type,
    )


def prepare_decision_transition(
    provider: DecisionProvider,
    state: SimulationState,
    decision_point_id: DecisionPointId,
    transition_ref: TransitionRef,
    event_ids: Sequence[EventId],
    *,
    base_history: Sequence[CommittedTransition],
    provider_source_ref: ProvenanceSourceRef | None = None,
    provider_metadata: Mapping[str, StructuredValue] | None = None,
    causation_refs: Sequence[CauseRef] = (),
    correlation_id: CorrelationId | None = None,
) -> PreparedCognitionTransition:
    """Invoke a provider and prepare one atomic Decision/Plan transition."""

    ids, causes, expected_head, logical_time = _validate_common(
        state,
        transition_ref,
        event_ids,
        base_history,
        causation_refs,
        correlation_id,
    )
    request = build_decision_request(state, decision_point_id)
    provenance = Provenance(
        "DECISION_PROVIDER",
        provider_source_ref,
        {} if provider_metadata is None else provider_metadata,
    )
    try:
        proposal = provider.decide(request)
    except Exception as error:
        raise DeterministicDecisionIntegrityError(
            "deterministic DecisionProvider failed"
        ) from error
    if type(proposal) is not DecisionProposal:
        raise DeterministicDecisionIntegrityError(
            "deterministic DecisionProvider returned invalid output"
        )

    try:
        materialized = _materialized_plan(request, proposal, provenance, logical_time)
        specs: list[EventSpec] = [
            (
                DECISION_RECORDED,
                _decision_payload(decision_point_id, proposal),
                provenance,
                causes,
            )
        ]
        if materialized is not None:
            if len(ids) < 2:
                raise CognitionValidationError(
                    "Plan decision requires DecisionRecorded and Plan Event identities"
                )
            plan, event_type = materialized
            specs.append(
                (
                    event_type,
                    _plan_payload(plan),
                    provenance,
                    (CauseRef("event", ids[0].value),),
                )
            )
        transition = _candidate_transition(
            transition_ref, logical_time, ids, tuple(specs), correlation_id
        )
        _project_candidate(state, transition)
    except (CognitionValidationError, TypeError, ValueError) as error:
        raise DeterministicDecisionIntegrityError(
            "deterministic DecisionProvider returned an invalid proposal"
        ) from error
    return PreparedCognitionTransition(expected_head, transition)
