# SPDX-License-Identifier: GPL-3.0-only

"""Immutable Observation, DecisionPoint, and Decision value contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, TypeAlias

from grass.core._structured_data import (
    StructuredValue,
    freeze_structured_mapping,
    freeze_structured_value,
)
from grass.core.execution import PlanRef, PlanStep
from grass.core.identifiers import (
    DecisionPointId,
    EntityId,
    ObservationId,
    PlanId,
    PlanStepId,
)
from grass.core.logical_time import LogicalTime
from grass.core.provenance import Provenance


def _non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


def _positive_version(value: object) -> None:
    if type(value) is not int:
        raise TypeError("Plan version must be an integer")
    if value < 1:
        raise ValueError("Plan version must be positive")


class DecisionPointReason(StrEnum):
    PLAN_REQUIRED = "PLAN_REQUIRED"
    PLAN_EXHAUSTED = "PLAN_EXHAUSTED"
    PLAN_BLOCKED = "PLAN_BLOCKED"
    INTERACTION_REQUEST = "INTERACTION_REQUEST"
    JOB_FAILED = "JOB_FAILED"
    JOB_PAUSED = "JOB_PAUSED"
    ASSUMPTION_INVALIDATED = "ASSUMPTION_INVALIDATED"
    MATERIAL_OBSERVATION = "MATERIAL_OBSERVATION"
    EXTERNAL_EVENT = "EXTERNAL_EVENT"
    OPERATOR_INTERVENTION = "OPERATOR_INTERVENTION"


class DecisionPointScope(StrEnum):
    FULL = "FULL"
    BOUNDED = "BOUNDED"


class DecisionOutcomeKind(StrEnum):
    CONTINUE_PLAN = "CONTINUE_PLAN"
    REVISE_PLAN = "REVISE_PLAN"
    REPLACE_PLAN = "REPLACE_PLAN"
    BOUNDED_REACTION = "BOUNDED_REACTION"


@dataclass(frozen=True, slots=True)
class Observation:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    observation_id: ObservationId
    actor_id: EntityId
    content: Mapping[str, StructuredValue]
    provenance: Provenance
    observed_at: LogicalTime

    def __post_init__(self) -> None:
        if type(self.observation_id) is not ObservationId:
            raise TypeError("observation_id must be an ObservationId")
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        if not isinstance(self.content, Mapping):
            raise TypeError("content must be a mapping")
        if type(self.provenance) is not Provenance:
            raise TypeError("provenance must be Provenance")
        if type(self.observed_at) is not LogicalTime:
            raise TypeError("observed_at must be LogicalTime")
        object.__setattr__(
            self,
            "content",
            freeze_structured_mapping(self.content, description="Observation content"),
        )


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    decision_point_id: DecisionPointId
    actor_id: EntityId
    reason: DecisionPointReason
    scope: DecisionPointScope
    observation_ids: frozenset[ObservationId]
    subject_plan_ref: PlanRef | None = None

    def __post_init__(self) -> None:
        if type(self.decision_point_id) is not DecisionPointId:
            raise TypeError("decision_point_id must be a DecisionPointId")
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
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
class BoundedReaction:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    intent_description: str
    content: StructuredValue | None = None

    def __post_init__(self) -> None:
        _non_empty_string(self.intent_description, "intent_description")
        object.__setattr__(
            self,
            "content",
            freeze_structured_value(self.content, description="BoundedReaction content"),
        )


@dataclass(frozen=True, slots=True)
class ContinuePlanDecision:
    kind: ClassVar[DecisionOutcomeKind] = DecisionOutcomeKind.CONTINUE_PLAN


@dataclass(frozen=True, slots=True)
class RevisePlanDecision:
    kind: ClassVar[DecisionOutcomeKind] = DecisionOutcomeKind.REVISE_PLAN
    resulting_plan_ref: PlanRef

    def __post_init__(self) -> None:
        if type(self.resulting_plan_ref) is not PlanRef:
            raise TypeError("resulting_plan_ref must be a PlanRef")


@dataclass(frozen=True, slots=True)
class ReplacePlanDecision:
    kind: ClassVar[DecisionOutcomeKind] = DecisionOutcomeKind.REPLACE_PLAN
    resulting_plan_ref: PlanRef

    def __post_init__(self) -> None:
        if type(self.resulting_plan_ref) is not PlanRef:
            raise TypeError("resulting_plan_ref must be a PlanRef")


@dataclass(frozen=True, slots=True)
class BoundedReactionDecision:
    kind: ClassVar[DecisionOutcomeKind] = DecisionOutcomeKind.BOUNDED_REACTION
    bounded_reaction: BoundedReaction

    def __post_init__(self) -> None:
        if type(self.bounded_reaction) is not BoundedReaction:
            raise TypeError("bounded_reaction must be a BoundedReaction")


DecisionOutcome: TypeAlias = (
    ContinuePlanDecision | RevisePlanDecision | ReplacePlanDecision | BoundedReactionDecision
)


@dataclass(frozen=True, slots=True)
class Decision:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    decision_point_id: DecisionPointId
    outcome: DecisionOutcome
    provenance: Provenance
    recorded_at: LogicalTime

    def __post_init__(self) -> None:
        if type(self.decision_point_id) is not DecisionPointId:
            raise TypeError("decision_point_id must be a DecisionPointId")
        if type(self.outcome) not in (
            ContinuePlanDecision,
            RevisePlanDecision,
            ReplacePlanDecision,
            BoundedReactionDecision,
        ):
            raise TypeError("outcome must be a supported DecisionOutcome")
        if type(self.provenance) is not Provenance:
            raise TypeError("provenance must be Provenance")
        if type(self.recorded_at) is not LogicalTime:
            raise TypeError("recorded_at must be LogicalTime")


def _validate_steps(steps: tuple[PlanStep, ...]) -> None:
    if not steps:
        raise ValueError("a ProposedPlan must contain at least one PlanStep")
    step_ids = tuple(step.step_id for step in steps)
    if len(set(step_ids)) != len(step_ids):
        raise ValueError("PlanStepId values must be unique within a ProposedPlan")
    known = frozenset(step_ids)
    for step in steps:
        if any(dependency.step_id not in known for dependency in step.dependencies):
            raise ValueError("ProposedPlan dependencies must target its own steps")

    dependencies = {
        step.step_id: frozenset(item.step_id for item in step.dependencies) for step in steps
    }
    visiting: set[PlanStepId] = set()
    visited: set[PlanStepId] = set()

    def visit(step_id: PlanStepId) -> None:
        if step_id in visiting:
            raise ValueError("ProposedPlan dependencies must form a DAG")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency_id in dependencies[step_id]:
            visit(dependency_id)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in step_ids:
        visit(step_id)


@dataclass(frozen=True, slots=True)
class ProposedPlan:
    """Untrusted complete semantic Plan content without Event envelope fields."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    plan_id: PlanId
    version: int
    actor_id: EntityId
    objective: str
    steps: Sequence[PlanStep]
    replaces_plan_ref: PlanRef | None

    def __post_init__(self) -> None:
        if type(self.plan_id) is not PlanId:
            raise TypeError("plan_id must be a PlanId")
        _positive_version(self.version)
        if type(self.actor_id) is not EntityId:
            raise TypeError("actor_id must be an EntityId")
        _non_empty_string(self.objective, "objective")
        steps = tuple(self.steps)
        if not all(type(step) is PlanStep for step in steps):
            raise TypeError("steps must contain only PlanStep values")
        _validate_steps(steps)
        if self.replaces_plan_ref is not None and type(self.replaces_plan_ref) is not PlanRef:
            raise TypeError("replaces_plan_ref must be a PlanRef or None")
        if self.replaces_plan_ref is not None and self.replaces_plan_ref.plan_id == self.plan_id:
            raise ValueError("a ProposedPlan cannot replace its own PlanId")
        object.__setattr__(self, "steps", steps)

    @property
    def ref(self) -> PlanRef:
        return PlanRef(self.plan_id, self.version)
