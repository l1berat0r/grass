# SPDX-License-Identifier: GPL-3.0-only

"""Immutable authoritative simulation-state projection contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import ClassVar, Literal, TypeAlias

from grass.core._structured_data import (
    StructuredValue,
    freeze_structured_mapping,
    freeze_structured_value,
)
from grass.core.cognition import (
    BoundedReactionDecision,
    ContinuePlanDecision,
    Decision,
    DecisionPoint,
    Observation,
    ReplacePlanDecision,
    RevisePlanDecision,
)
from grass.core.execution import Job, Plan, PlanRef
from grass.core.identifiers import (
    BranchId,
    DecisionPointId,
    EntityId,
    JobId,
    ObservationId,
    PlanId,
    PlanStepId,
    RelationId,
)
from grass.core.logical_time import LogicalTime
from grass.core.references import TransitionRef


def _require_non_empty_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if value == "":
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class RelationParticipant:
    """One role binding in an unordered Relation participant set."""

    role: str
    entity_id: EntityId

    def __post_init__(self) -> None:
        _require_non_empty_string(self.role, "role")
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")


@dataclass(frozen=True, slots=True)
class WorldScope:
    """The single world-wide StateVariable scope."""

    kind: Literal["WORLD"] = field(default="WORLD", init=False)


@dataclass(frozen=True, slots=True)
class EntityScope:
    """A StateVariable scope associated with one Entity."""

    entity_id: EntityId
    kind: Literal["ENTITY"] = field(default="ENTITY", init=False)

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")


StateVariableScope: TypeAlias = WorldScope | EntityScope


@dataclass(frozen=True, slots=True)
class ResourceKey:
    entity_id: EntityId
    resource_type: str

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _require_non_empty_string(self.resource_type, "resource_type")


@dataclass(frozen=True, slots=True)
class StateVariableKey:
    scope: StateVariableScope
    state_variable_type: str

    def __post_init__(self) -> None:
        if type(self.scope) not in (WorldScope, EntityScope):
            raise TypeError("scope must be a WorldScope or EntityScope")
        _require_non_empty_string(self.state_variable_type, "state_variable_type")


@dataclass(frozen=True, slots=True)
class Entity:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entity_id: EntityId
    entity_type: str
    properties: Mapping[str, StructuredValue]
    active: bool = True

    def __post_init__(self) -> None:
        if type(self.entity_id) is not EntityId:
            raise TypeError("entity_id must be an EntityId")
        _require_non_empty_string(self.entity_type, "entity_type")
        if not isinstance(self.properties, Mapping):
            raise TypeError("properties must be a mapping")
        if type(self.active) is not bool:
            raise TypeError("active must be a boolean")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="Entity properties"),
        )


@dataclass(frozen=True, slots=True)
class Relation:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    relation_id: RelationId
    relation_type: str
    participants: frozenset[RelationParticipant]
    properties: Mapping[str, StructuredValue]
    active: bool = True

    def __post_init__(self) -> None:
        if type(self.relation_id) is not RelationId:
            raise TypeError("relation_id must be a RelationId")
        _require_non_empty_string(self.relation_type, "relation_type")
        if type(self.participants) is not frozenset:
            raise TypeError("participants must be a frozenset")
        if not self.participants:
            raise ValueError("participants must not be empty")
        if not all(type(item) is RelationParticipant for item in self.participants):
            raise TypeError("participants must contain RelationParticipant values")
        if not isinstance(self.properties, Mapping):
            raise TypeError("properties must be a mapping")
        if type(self.active) is not bool:
            raise TypeError("active must be a boolean")
        object.__setattr__(
            self,
            "properties",
            freeze_structured_mapping(self.properties, description="Relation properties"),
        )


ResourceQuantity: TypeAlias = int | float


@dataclass(frozen=True, slots=True)
class WorldState:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    entities: Mapping[EntityId, Entity] = field(default_factory=dict)
    relations: Mapping[RelationId, Relation] = field(default_factory=dict)
    resources: Mapping[ResourceKey, ResourceQuantity] = field(default_factory=dict)
    state_variables: Mapping[StateVariableKey, StructuredValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        entities = dict(self.entities)
        relations = dict(self.relations)
        resources = dict(self.resources)
        state_variables = dict(self.state_variables)

        for entity_id, entity in entities.items():
            if type(entity_id) is not EntityId or type(entity) is not Entity:
                raise TypeError("entities must map EntityId to Entity")
            if entity_id != entity.entity_id:
                raise ValueError("Entity key must match entity_id")
        for relation_id, relation in relations.items():
            if type(relation_id) is not RelationId or type(relation) is not Relation:
                raise TypeError("relations must map RelationId to Relation")
            if relation_id != relation.relation_id:
                raise ValueError("Relation key must match relation_id")
            if any(item.entity_id not in entities for item in relation.participants):
                raise ValueError("Relation participants must reference existing Entities")
        for resource_key, quantity in resources.items():
            if type(resource_key) is not ResourceKey:
                raise TypeError("resource keys must be ResourceKey values")
            if resource_key.entity_id not in entities:
                raise ValueError("Resources must reference existing Entities")
            if type(quantity) not in (int, float) or (
                type(quantity) is float and not isfinite(quantity)
            ):
                raise TypeError("Resource quantity must be an integer or finite float")
        frozen_state_variables: dict[StateVariableKey, StructuredValue] = {}
        for variable_key, value in state_variables.items():
            if type(variable_key) is not StateVariableKey:
                raise TypeError("state variable keys must be StateVariableKey values")
            if (
                type(variable_key.scope) is EntityScope
                and variable_key.scope.entity_id not in entities
            ):
                raise ValueError("Entity-scoped values must reference existing Entities")
            frozen_state_variables[variable_key] = freeze_structured_value(
                value, description="StateVariable value"
            )

        object.__setattr__(self, "entities", MappingProxyType(entities))
        object.__setattr__(self, "relations", MappingProxyType(relations))
        object.__setattr__(self, "resources", MappingProxyType(resources))
        object.__setattr__(self, "state_variables", MappingProxyType(frozen_state_variables))


@dataclass(frozen=True, slots=True)
class ExecutionState:
    """Immutable projection of persistent Plan and Job state."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    plans: Mapping[PlanRef, Plan] = field(default_factory=dict)
    jobs: Mapping[JobId, Job] = field(default_factory=dict)

    def __post_init__(self) -> None:
        plans = dict(self.plans)
        jobs = dict(self.jobs)

        versions_by_plan: dict[PlanId, set[int]] = {}
        step_owners: dict[PlanStepId, PlanId] = {}
        for plan_ref, plan in plans.items():
            if type(plan_ref) is not PlanRef or type(plan) is not Plan:
                raise TypeError("plans must map PlanRef to Plan")
            if plan_ref != plan.ref:
                raise ValueError("Plan key must match Plan.ref")
            versions_by_plan.setdefault(plan.plan_id, set()).add(plan.version)
            for step in plan.steps:
                owner = step_owners.setdefault(step.step_id, plan.plan_id)
                if owner != plan.plan_id:
                    raise ValueError("PlanStepId cannot belong to more than one PlanId")

        latest_by_plan: dict[PlanId, PlanRef] = {}
        for plan_id, versions in versions_by_plan.items():
            latest_version = max(versions)
            if versions != set(range(1, latest_version + 1)):
                raise ValueError("Plan versions must be contiguous from version 1")
            latest_by_plan[plan_id] = PlanRef(plan_id, latest_version)

            first = plans[PlanRef(plan_id, 1)]
            for version in range(2, latest_version + 1):
                if plans[PlanRef(plan_id, version)].replaces_plan_ref != first.replaces_plan_ref:
                    raise ValueError("Plan revisions must preserve replaces_plan_ref")

        replaced_by: dict[PlanId, PlanId] = {}
        for plan_id in versions_by_plan:
            first = plans[PlanRef(plan_id, 1)]
            replaced = first.replaces_plan_ref
            if replaced is None:
                continue
            if replaced not in plans:
                raise ValueError("replacement must reference an existing Plan")
            if latest_by_plan[replaced.plan_id] != replaced:
                raise ValueError("replacement must reference the latest Plan version")
            if replaced.plan_id in replaced_by:
                raise ValueError("a PlanId cannot be replaced more than once")
            replaced_by[replaced.plan_id] = plan_id

        for starting_plan_id in replaced_by:
            seen: set[PlanId] = set()
            plan_id = starting_plan_id
            while plan_id in replaced_by:
                if plan_id in seen:
                    raise ValueError("Plan replacements must not form a cycle")
                seen.add(plan_id)
                plan_id = replaced_by[plan_id]

        jobs_by_step: dict[PlanStepId, JobId] = {}
        for job_id, job in jobs.items():
            if type(job_id) is not JobId or type(job) is not Job:
                raise TypeError("jobs must map JobId to Job")
            if job_id != job.job_id:
                raise ValueError("Job key must match job_id")
            referenced_plan = plans.get(job.plan_step_ref.plan_ref)
            if referenced_plan is None or referenced_plan.step(job.plan_step_ref.step_id) is None:
                raise ValueError("Job must reference an existing exact PlanStep")
            previous_job_id = jobs_by_step.setdefault(job.plan_step_ref.step_id, job_id)
            if previous_job_id != job_id:
                raise ValueError("a logical PlanStep may have at most one Job")

        object.__setattr__(self, "plans", MappingProxyType(plans))
        object.__setattr__(self, "jobs", MappingProxyType(jobs))


@dataclass(frozen=True, slots=True)
class CognitionState:
    """Immutable projection of material actor cognition state."""

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    observations: Mapping[ObservationId, Observation] = field(default_factory=dict)
    decision_points: Mapping[DecisionPointId, DecisionPoint] = field(default_factory=dict)
    decisions: Mapping[DecisionPointId, Decision] = field(default_factory=dict)

    def __post_init__(self) -> None:
        observations = dict(self.observations)
        decision_points = dict(self.decision_points)
        decisions = dict(self.decisions)
        for observation_id, observation in observations.items():
            if type(observation_id) is not ObservationId or type(observation) is not Observation:
                raise TypeError("observations must map ObservationId to Observation")
            if observation_id != observation.observation_id:
                raise ValueError("Observation key must match observation_id")
        for decision_point_id, decision_point in decision_points.items():
            if (
                type(decision_point_id) is not DecisionPointId
                or type(decision_point) is not DecisionPoint
            ):
                raise TypeError("decision_points must map DecisionPointId to DecisionPoint")
            if decision_point_id != decision_point.decision_point_id:
                raise ValueError("DecisionPoint key must match decision_point_id")
            if any(item not in observations for item in decision_point.observation_ids):
                raise ValueError("DecisionPoint must reference existing Observations")
            if any(
                observations[item].actor_id != decision_point.actor_id
                for item in decision_point.observation_ids
            ):
                raise ValueError("DecisionPoint Observations must belong to its actor")
        for decision_point_id, decision in decisions.items():
            if type(decision_point_id) is not DecisionPointId or type(decision) is not Decision:
                raise TypeError("decisions must map DecisionPointId to Decision")
            if decision_point_id != decision.decision_point_id:
                raise ValueError("Decision key must match decision_point_id")
            if decision_point_id not in decision_points:
                raise ValueError("Decision must reference an existing DecisionPoint")

        object.__setattr__(self, "observations", MappingProxyType(observations))
        object.__setattr__(self, "decision_points", MappingProxyType(decision_points))
        object.__setattr__(self, "decisions", MappingProxyType(decisions))

    def is_pending(self, decision_point_id: DecisionPointId) -> bool:
        """Return whether an existing DecisionPoint has no accepted Decision."""

        if type(decision_point_id) is not DecisionPointId:
            raise TypeError("decision_point_id must be a DecisionPointId")
        if decision_point_id not in self.decision_points:
            raise KeyError(decision_point_id)
        return decision_point_id not in self.decisions


@dataclass(frozen=True, slots=True)
class ProjectionPosition:
    branch_id: BranchId
    last_transition_ref: TransitionRef | None = None
    last_sequence: int = 0
    logical_time: LogicalTime | None = None

    def __post_init__(self) -> None:
        if type(self.branch_id) is not BranchId:
            raise TypeError("branch_id must be a BranchId")
        if type(self.last_sequence) is not int:
            raise TypeError("last_sequence must be an integer")
        if self.last_transition_ref is None:
            if self.last_sequence != 0 or self.logical_time is not None:
                raise ValueError("empty projection position must use sequence zero and no time")
            return
        if type(self.last_transition_ref) is not TransitionRef:
            raise TypeError("last_transition_ref must be a TransitionRef or None")
        if self.last_transition_ref.branch_id != self.branch_id:
            raise ValueError("projection and transition branches must match")
        if self.last_sequence < 1 or type(self.logical_time) is not LogicalTime:
            raise ValueError("non-empty projection position must be complete")


@dataclass(frozen=True, slots=True)
class SimulationState:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: ProjectionPosition
    world: WorldState = field(default_factory=WorldState)
    execution: ExecutionState = field(default_factory=ExecutionState)
    cognition: CognitionState = field(default_factory=CognitionState)

    def __post_init__(self) -> None:
        if type(self.position) is not ProjectionPosition:
            raise TypeError("position must be a ProjectionPosition")
        if type(self.world) is not WorldState:
            raise TypeError("world must be a WorldState")
        if type(self.execution) is not ExecutionState:
            raise TypeError("execution must be an ExecutionState")
        if type(self.cognition) is not CognitionState:
            raise TypeError("cognition must be a CognitionState")
        if any(plan.actor_id not in self.world.entities for plan in self.execution.plans.values()):
            raise ValueError("Plan actors must reference existing Entities")
        if any(
            observation.actor_id not in self.world.entities
            for observation in self.cognition.observations.values()
        ):
            raise ValueError("Observation actors must reference existing Entities")
        if any(
            point.actor_id not in self.world.entities
            for point in self.cognition.decision_points.values()
        ):
            raise ValueError("DecisionPoint actors must reference existing Entities")
        for point in self.cognition.decision_points.values():
            if point.subject_plan_ref is None:
                continue
            plan = self.execution.plans.get(point.subject_plan_ref)
            if plan is None or plan.actor_id != point.actor_id:
                raise ValueError("DecisionPoint subject must be an exact same-actor Plan")
        for decision_point_id, decision in self.cognition.decisions.items():
            point = self.cognition.decision_points[decision_point_id]
            outcome = decision.outcome
            subject = point.subject_plan_ref
            if type(outcome) is ContinuePlanDecision:
                if subject is None:
                    raise ValueError("CONTINUE_PLAN requires an exact subject Plan")
                continue
            if type(outcome) is BoundedReactionDecision:
                continue
            if not isinstance(outcome, (RevisePlanDecision, ReplacePlanDecision)):
                raise AssertionError("unsupported DecisionOutcome")
            resulting_ref = outcome.resulting_plan_ref
            plan = self.execution.plans.get(resulting_ref)
            if plan is None or plan.actor_id != point.actor_id:
                raise ValueError("Decision resulting Plan must exist and belong to its actor")
            if type(outcome) is RevisePlanDecision:
                if subject is None or resulting_ref != PlanRef(
                    subject.plan_id, subject.version + 1
                ):
                    raise ValueError("REVISE_PLAN must identify the next subject Plan version")
            elif type(outcome) is ReplacePlanDecision:
                if (
                    resulting_ref.version != 1
                    or plan.replaces_plan_ref != subject
                    or (subject is not None and resulting_ref.plan_id == subject.plan_id)
                ):
                    raise ValueError("REPLACE_PLAN must preserve its exact subject relationship")

    @classmethod
    def empty(cls, branch_id: BranchId) -> SimulationState:
        return cls(position=ProjectionPosition(branch_id=branch_id))
