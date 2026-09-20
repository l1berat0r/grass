# SPDX-License-Identifier: GPL-3.0-only

"""Immutable transport-neutral application and query contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from grass.core.branches import Branch, HistoryPosition
from grass.core.cognition import Decision, DecisionPoint, Observation
from grass.core.events import CommittedTransition
from grass.core.execution import Job, Plan, PlanStep
from grass.core.identifiers import EntityId, EventId
from grass.core.logical_time import LogicalTime
from grass.core.state import Entity, SimulationState
from grass.core.world_definitions import SimulationRunConfig, WorldDefinition
from grass.persistence.contracts import (
    RunId,
    SimulationRunRecord,
    WorldMaterialKind,
)


class QueryError(RuntimeError):
    """A read-only application query cannot produce a valid view."""


class QueryNotFoundError(QueryError, LookupError):
    """A requested run, branch, or projected value does not exist."""


class VerificationIntegrityError(RuntimeError):
    """Persisted run material or canonical history is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class RunView:
    record: SimulationRunRecord
    definition: WorldDefinition
    config: SimulationRunConfig

    def __post_init__(self) -> None:
        if type(self.record) is not SimulationRunRecord:
            raise TypeError("record must be a SimulationRunRecord")
        if type(self.definition) is not WorldDefinition:
            raise TypeError("definition must be a WorldDefinition")
        if type(self.config) is not SimulationRunConfig:
            raise TypeError("config must be a SimulationRunConfig")
        if self.record.world_definition_ref != self.definition.ref:
            raise ValueError("record must reference definition")
        if self.config.world_definition_ref != self.definition.ref:
            raise ValueError("config must reference definition")


@dataclass(frozen=True, slots=True)
class QueryPosition:
    run_id: RunId
    history_position: HistoryPosition
    logical_time: LogicalTime

    def __post_init__(self) -> None:
        if type(self.run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        if type(self.history_position) is not HistoryPosition:
            raise TypeError("history_position must be a HistoryPosition")
        if type(self.logical_time) is not LogicalTime:
            raise TypeError("logical_time must be a LogicalTime")


@dataclass(frozen=True, slots=True)
class BranchView:
    position: QueryPosition
    branch: Branch
    visible_transition_count: int
    origin_transition_count: int

    def __post_init__(self) -> None:
        if type(self.position) is not QueryPosition:
            raise TypeError("position must be a QueryPosition")
        if type(self.branch) is not Branch:
            raise TypeError("branch must be a Branch")
        if self.position.history_position.branch_id != self.branch.branch_id:
            raise ValueError("position must view branch")
        for name in ("visible_transition_count", "origin_transition_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.origin_transition_count > self.visible_transition_count:
            raise ValueError("origin transition count cannot exceed visible transition count")


class HistoryScope(StrEnum):
    VISIBLE = "VISIBLE"
    BRANCH_ORIGIN = "BRANCH_ORIGIN"


@dataclass(frozen=True, slots=True)
class HistoryView:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: QueryPosition
    scope: HistoryScope
    transitions: Sequence[CommittedTransition]

    def __post_init__(self) -> None:
        if type(self.position) is not QueryPosition:
            raise TypeError("position must be a QueryPosition")
        if type(self.scope) is not HistoryScope:
            raise TypeError("scope must be a HistoryScope")
        transitions = tuple(self.transitions)
        if not all(type(item) is CommittedTransition for item in transitions):
            raise TypeError("transitions must contain CommittedTransition values")
        object.__setattr__(self, "transitions", transitions)


@dataclass(frozen=True, slots=True)
class StateView:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: QueryPosition
    state: SimulationState

    def __post_init__(self) -> None:
        if type(self.position) is not QueryPosition:
            raise TypeError("position must be a QueryPosition")
        if type(self.state) is not SimulationState:
            raise TypeError("state must be a SimulationState")


@dataclass(frozen=True, slots=True)
class JobView:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: QueryPosition
    job: Job
    plan: Plan
    step: PlanStep

    def __post_init__(self) -> None:
        if type(self.position) is not QueryPosition:
            raise TypeError("position must be a QueryPosition")
        if type(self.job) is not Job:
            raise TypeError("job must be a Job")
        if type(self.plan) is not Plan:
            raise TypeError("plan must be a Plan")
        if type(self.step) is not PlanStep:
            raise TypeError("step must be a PlanStep")
        if self.job.plan_step_ref.plan_ref != self.plan.ref:
            raise ValueError("job must reference exact plan")
        if self.job.plan_step_ref.step_id != self.step.step_id:
            raise ValueError("job must reference exact step")


class DecisionStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True, slots=True)
class DecisionView:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: QueryPosition
    decision_point: DecisionPoint
    status: DecisionStatus
    decision: Decision | None = None

    def __post_init__(self) -> None:
        if type(self.position) is not QueryPosition:
            raise TypeError("position must be a QueryPosition")
        if type(self.decision_point) is not DecisionPoint:
            raise TypeError("decision_point must be a DecisionPoint")
        if type(self.status) is not DecisionStatus:
            raise TypeError("status must be a DecisionStatus")
        if self.decision is not None and type(self.decision) is not Decision:
            raise TypeError("decision must be a Decision or None")
        if (self.decision is None) != (self.status is DecisionStatus.PENDING):
            raise ValueError("decision presence must match status")
        if (
            self.decision is not None
            and self.decision.decision_point_id != self.decision_point.decision_point_id
        ):
            raise ValueError("decision must resolve decision_point")


class ActorMembershipEvidence(StrEnum):
    PLAN = "PLAN"
    OBSERVATION = "OBSERVATION"
    DECISION_POINT = "DECISION_POINT"


@dataclass(frozen=True, slots=True)
class ActorView:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    position: QueryPosition
    entity: Entity
    evidence: Sequence[ActorMembershipEvidence]
    plans: Sequence[Plan]
    observations: Sequence[Observation]
    decisions: Sequence[DecisionView]
    jobs: Sequence[JobView]

    def __post_init__(self) -> None:
        if type(self.position) is not QueryPosition:
            raise TypeError("position must be a QueryPosition")
        if type(self.entity) is not Entity:
            raise TypeError("entity must be an Entity")
        evidence = tuple(self.evidence)
        plans = tuple(self.plans)
        observations = tuple(self.observations)
        decisions = tuple(self.decisions)
        jobs = tuple(self.jobs)
        if not evidence or not all(type(item) is ActorMembershipEvidence for item in evidence):
            raise TypeError("evidence must contain ActorMembershipEvidence values")
        if len(set(evidence)) != len(evidence):
            raise ValueError("evidence must be unique")
        if not all(type(item) is Plan for item in plans):
            raise TypeError("plans must contain Plan values")
        if not all(type(item) is Observation for item in observations):
            raise TypeError("observations must contain Observation values")
        if not all(type(item) is DecisionView for item in decisions):
            raise TypeError("decisions must contain DecisionView values")
        if not all(type(item) is JobView for item in jobs):
            raise TypeError("jobs must contain JobView values")
        actor_id = self.entity.entity_id
        if any(item.actor_id != actor_id for item in plans):
            raise ValueError("plans must belong to actor")
        if any(item.actor_id != actor_id for item in observations):
            raise ValueError("observations must belong to actor")
        if any(item.decision_point.actor_id != actor_id for item in decisions):
            raise ValueError("decisions must belong to actor")
        if any(item.plan.actor_id != actor_id for item in jobs):
            raise ValueError("jobs must belong to actor")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "plans", plans)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "jobs", jobs)

    @property
    def actor_id(self) -> EntityId:
        return self.entity.entity_id


class ActorHistoryAttributionKind(StrEnum):
    OBSERVATION = "OBSERVATION"
    DECISION_POINT = "DECISION_POINT"
    DECISION = "DECISION"
    PLAN = "PLAN"
    JOB = "JOB"
    JOB_RESOLUTION = "JOB_RESOLUTION"


@dataclass(frozen=True, slots=True)
class ActorHistoryAttribution:
    event_id: EventId
    kind: ActorHistoryAttributionKind

    def __post_init__(self) -> None:
        if type(self.event_id) is not EventId:
            raise TypeError("event_id must be an EventId")
        if type(self.kind) is not ActorHistoryAttributionKind:
            raise TypeError("kind must be an ActorHistoryAttributionKind")


@dataclass(frozen=True, slots=True)
class ActorHistoryEntry:
    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    transition: CommittedTransition
    attributions: Sequence[ActorHistoryAttribution]

    def __post_init__(self) -> None:
        if type(self.transition) is not CommittedTransition:
            raise TypeError("transition must be a CommittedTransition")
        attributions = tuple(self.attributions)
        if not attributions or not all(
            type(item) is ActorHistoryAttribution for item in attributions
        ):
            raise TypeError("attributions must contain ActorHistoryAttribution values")
        event_ids = frozenset(event.event_id for event in self.transition.events)
        if any(item.event_id not in event_ids for item in attributions):
            raise ValueError("attributions must reference Events in transition")
        object.__setattr__(self, "attributions", attributions)


@dataclass(frozen=True, slots=True)
class VerificationReport:
    run_id: RunId
    world_material_kind: WorldMaterialKind
    branch_count: int
    transition_count: int
    event_count: int
    snapshot_file_count: int | None

    def __post_init__(self) -> None:
        if type(self.run_id) is not RunId:
            raise TypeError("run_id must be a RunId")
        if type(self.world_material_kind) is not WorldMaterialKind:
            raise TypeError("world_material_kind must be a WorldMaterialKind")
        for name in ("branch_count", "transition_count", "event_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.snapshot_file_count is not None and (
            type(self.snapshot_file_count) is not int or self.snapshot_file_count < 0
        ):
            raise ValueError("snapshot_file_count must be a non-negative integer or None")
        if (self.world_material_kind is WorldMaterialKind.PACKAGE_SNAPSHOT) != (
            self.snapshot_file_count is not None
        ):
            raise ValueError("snapshot_file_count must match world material kind")
